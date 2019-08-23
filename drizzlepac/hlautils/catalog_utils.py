"""This script contains code to support creation of photometric sourcelists using two techniques: aperture photometry
segmentation-map based photometry.
"""
import sys

import astropy.units as u
from astropy.io import fits as fits
from astropy.convolution import Gaussian2DKernel, MexicanHat2DKernel
from astropy.stats import mad_std, gaussian_fwhm_to_sigma, gaussian_sigma_to_fwhm
from astropy.table import Column, MaskedColumn, Table
import numpy as np
from scipy import ndimage

from photutils import aperture_photometry, CircularAperture, CircularAnnulus, DAOStarFinder
from photutils import Background2D, SExtractorBackground, StdBackgroundRMS
from photutils import detect_sources, source_properties  # , deblend_sources
from stsci.tools import logutil
from stwcs.wcsutil import HSTWCS

from . import astrometric_utils
from . import photometry_tools

try:
    from matplotlib import pyplot as plt
except Exception:
    plt = None

# Default background determination parameter values
BKG_BOX_SIZE = 50
BKG_FILTER_SIZE = 3
CATALOG_TYPES = ['aperture', 'segment']

__taskname__ = 'catalog_utils'

log = logutil.create_logger(__name__, level=logutil.logging.INFO, stream=sys.stdout)


# ======================================================================================================================
class ParamDict:
    full_param_dict = {
        "ACS HRC": {
            "astrodrizzle": {
                "SCALE": 0.025,
                "PIXFRAC": 1.0,
                "KERNEL": "square",
                "OUTNX": None,
                "OUTNY": None,
                "ROT": 0.0,
                "BITS": 256},
            "ci filter": {
                "ci_daolower_limit": 0.9,
                "ci_daoupper_limit": 1.6,
                "ci_selower_limit": 0.9,
                "ci_seupper_limit": 1.6},
            "dao": {
                "TWEAK_FWHMPSF": 0.073,
                "TWEAK_THRESHOLD": 3.0,
                "aperture_1": 0.03,
                "aperture_2": 0.125,
                "bthresh": 5.0},
            "sourcex": {
                "fwhm": 0.073,
                "thresh": 1.4,
                "bthresh": 5.0,
                "source_box": 7},
            "swarm filter": {
                "upper_epp_limit": 70000.,
                "lower_epp_limit": 2000.,
                "eppsky_limit": 1000.,
                "swarm_thresh": 1.,
                "clip_radius_list": [120.0, 100.0, 80.0, 60.0, 40.0, 20.0, 10.0, 5.0, 2.0, 0.0],
                "scale_factor_list": [0.0, 1.778106e-05, 3.821292e-05, 9.017166e-05, 2.725184e-04, 1.269197e-03, 7.007126e-03, 3.839166e-02, 2.553349e-01, 1.000000e+00],
                "proximity_binary": "no"}},
        "ACS SBC": {
            "astrodrizzle": {
                "SCALE": 0.03,
                "PIXFRAC": 1.0,
                "KERNEL": "square",
                "OUTNX": None,
                "OUTNY": None,
                "ROT": 0.0,
                "BITS": 256},
            "ci filter": {
                "ci_daolower_limit": 0.15,
                "ci_daoupper_limit": 0.45,
                "ci_selower_limit": 0.15,
                "ci_seupper_limit": 0.45},
            "dao": {
                "TWEAK_FWHMPSF": 0.065,
                "TWEAK_THRESHOLD": 3.0,
                "aperture_1": 0.07,
                "aperture_2": 0.125,
                "bthresh": 5.0},
            "sourcex": {
                "fwhm": 0.065,
                "thresh": 1.4,
                "bthresh": 5.0,
                "source_box": 7},
            "swarm filter": {
                "upper_epp_limit": 70000.,
                "lower_epp_limit": 2000.,
                "eppsky_limit": 1000.,
                "swarm_thresh": 1.,
                "clip_radius_list": [120.0, 100.0, 80.0, 60.0, 40.0, 20.0, 10.0, 5.0, 2.0, 0.0],
                "scale_factor_list": [0.0, 1.778106e-05, 3.821292e-05, 9.017166e-05, 2.725184e-04, 1.269197e-03, 7.007126e-03, 3.839166e-02, 2.553349e-01, 1.000000e+00],
                "proximity_binary": "no"}},
        "ACS WFC": {
            "astrodrizzle": {
                "SCALE": 0.05,
                "PIXFRAC": 1.0,
                "KERNEL": "square",
                "OUTNX": None,
                "OUTNY": None,
                "ROT": 0.0,
                "BITS": 256},
            "ci filter": {
                "ci_daolower_limit": 0.9,
                "ci_daoupper_limit": 1.23,
                "ci_selower_limit": 0.9,
                "ci_seupper_limit": 1.23},
            "dao": {
                "TWEAK_FWHMPSF": 0.076,
                "TWEAK_THRESHOLD": None,
                "aperture_1": 0.05,  # update from 0.15
                "aperture_2": 0.15,  # update from 0.25
                "bthresh": 1.5},
            "sourcex": {
                "fwhm": 0.13,
                "thresh": None,
                "bthresh": 5.0,
                "source_box": 5},
            "swarm filter": {
                "upper_epp_limit": 70000.,
                "lower_epp_limit": 2000.,
                "eppsky_limit": 1000.,
                "swarm_thresh": 1.,
                "clip_radius_list": [120., 100., 80., 60., 40., 30., 20., 10., 5., 2., 0.],
                "scale_factor_list": [0.0, 0.000000e+00, 6.498530e-06, 3.687270e-05, 1.412972e-04, 3.151877e-04, 1.023391e-03, 3.134859e-03, 2.602436e-02, 1.820539e-01, 1.000000e+00],
                "proximity_binary": "no"}},
        "WFC3 IR": {
            "astrodrizzle": {
                "SCALE": 0.09,
                "PIXFRAC": 1.0,
                "KERNEL": "square",
                "OUTNX": None,
                "OUTNY": None,
                "ROT": 0.0,
                "BITS": 768},
            "ci filter": {
                "ci_daolower_limit": 0.25,
                "ci_daoupper_limit": 0.55,
                "ci_selower_limit": 0.25,
                "ci_seupper_limit": 0.55},
            "dao": {
                "TWEAK_FWHMPSF": 0.14,
                "TWEAK_THRESHOLD": 3.0,
                "aperture_1": 0.15,
                "aperture_2": 0.45,
                "bthresh": 5.0},
            "sourcex": {
                "fwhm": 0.14,
                "thresh": 1.4,
                "bthresh": 5.0,
                "source_box": 7},
            "swarm filter": {
                "upper_epp_limit": 70000.,
                "lower_epp_limit": 2000.,
                "eppsky_limit": 100.,
                "swarm_thresh": 1.,
                "clip_radius_list": [140., 120., 100., 80., 60., 40., 20., 10., 5., 2., 0.],
                #                   x10    x10    x10   x10   x10   x10    x10   x10  x10  x2,
                "scale_factor_list": [1.5e-5, 2.3e-5, 4.e-5, 8.e-5, 2.e-4, 0.0006, 0.015, 0.05, 0.15, 0.9, 1.],
                # "scale_factor_list_orig": [1.5e-5, 2.3e-5, 4.e-5, 8.e-5, 2.e-4, 0.0006, 0.005, 0.05, 0.15, 0.9, 1.],
                "proximity_binary": "yes"}},
        "WFC3 UVIS": {
            "astrodrizzle": {
                "SCALE": 0.04,
                "PIXFRAC": 1.0,
                "KERNEL": "square",
                "OUTNX": None,
                "OUTNY": None,
                "ROT": 0.0,
                "BITS": 256},
            "ci filter": {
                "ci_daolower_limit": 0.75,
                "ci_daoupper_limit": 1.0,
                "ci_selower_limit": 0.75,
                "ci_seupper_limit": 1.0},
            "dao": {
                "TWEAK_FWHMPSF": 0.076,
                "TWEAK_THRESHOLD": 3.0,
                "aperture_1": 0.05,
                "aperture_2": 0.15,
                "bthresh": 5.0},
            "sourcex": {
                "fwhm": 0.076,
                "thresh": 1.4,
                "bthresh": 5.0,
                "source_box": 7},
            "swarm filter": {
                "upper_epp_limit": 70000.,
                "lower_epp_limit": 2000.,
                "eppsky_limit": 1000.,
                "swarm_thresh": 1.,
                "clip_radius_list": [120., 100., 80., 60., 40., 20., 10., 5., 2., 0.],
                "scale_factor_list": [2.3e-6, 4.e-6, 8.e-6, 2.e-5, 0.0005, 0.005, 0.005, 0.015, 0.45, 1.],
                # "scale_factor_list_orig": [2.3e-6, 4.e-6, 8.e-6, 2.e-5, 6.e-5, 0.0005, 0.005, 0.015, 0.45, 1.],
                "proximity_binary": "yes"}}}  # TODO: remove para_dict definition once we have fleshed out the config object

    def __init__(self, param_file=None):
        self.param_file = param_file

    def read_param_file(self):
        pass

    def get_params(self, instrument, detector):
        inst_det = "{} {}".format(instrument, detector)
        return self.full_param_dict[inst_det].copy()


class CatalogImage:
    def __init__(self, filename):
        if isinstance(filename, str):
            self.imghdu = fits.open(filename)
            self.imgname = filename
        else:
            self.imghdu = filename
            self.imgname = filename.filename()

        # Get header information to annotate the output catalogs
        if "total" in self.imgname:
            self.ghd_product = "tdp"
        else:
            self.ghd_product = "fdp"

        # Fits file read
        self.data = self.imghdu[('SCI', 1)].data
        self.wht_image = self.imghdu['WHT'].data.copy()

        # Get the HSTWCS object from the first extension
        self.imgwcs = HSTWCS(self.imghdu, 1)

        self.keyword_dict = self._get_header_data()

        self.bkg = None

    def close(self):
        self.imghdu.close()

    def build_kernel(self, fwhmpsf, scale):
        if self.bkg is None:
            self.compute_background()

        self.kernel = astrometric_utils.build_auto_kernel(self.data, self.wht_image,
                                                          threshold=self.bkg.background_rms, fwhm=fwhmpsf / scale)

    def compute_background(self, box_size=BKG_BOX_SIZE, win_size=BKG_FILTER_SIZE,
                           bkg_estimator=SExtractorBackground, rms_estimator=StdBackgroundRMS,
                           nsigma=5., threshold_flag=None):
        """Use Background2D to determine the background of the input image.

        Parameters
        ----------
        image : ndarray
            Numpy array of the science extension from the observations FITS file.

        box_size : int
            Size of box along each axis

        win_size : int
            Size of 2D filter to apply to the background image

        bkg_estimator : subroutine
            background estimation algorithm

        rms_estimator : subroutine
            RMS estimation algorithm

        nsigma : float
            Number of sigma above background

        threshold_flag : float or None
            Value from the image which serves as the limit for determining sources.
            If None, compute a default value of (background+5*rms(background)).
            If threshold < 0.0, use absolute value as scaling factor for default value.


        Returns
        -------
        bkg : 2D ndarray
            Background image

        bkg_dao_rms : ndarry
            Background RMS image

        threshold : ndarray
            Numpy array representing the background plus RMS

        """
        # Report configuration values to log
        log.info("")
        log.info("Computation of image background - Input Parameters")
        log.info("Box size: {}".format(box_size))
        log.info("Window size: {}".format(win_size))
        log.info("NSigma: {}".format(nsigma))

        # SExtractorBackground ans StdBackgroundRMS are the defaults
        bkg = None
        bkg_dao_rms = None

        exclude_percentiles = [10, 25, 50, 75]
        for percentile in exclude_percentiles:
            log.info("")
            log.info("Percentile in use: {}".format(percentile))
            try:
                bkg = Background2D(self.data, box_size, filter_size=win_size,
                                   bkg_estimator=bkg_estimator(),
                                   bkgrms_estimator=rms_estimator(),
                                   exclude_percentile=percentile, edge_method="pad")
            except Exception:
                bkg = None
                continue

            if bkg is not None:
                # Set the bkg_rms at "nsigma" sigma above background
                bkg_rms = nsigma * bkg.background_rms
                default_threshold = bkg.background + bkg_rms
                bkg_rms_mean = bkg.background.mean() + nsigma * bkg_rms.std()
                bkg_mean = bkg.background.mean()
                bkg_dao_rms = bkg.background_rms
                if threshold_flag is None:
                    threshold = default_threshold
                elif threshold_flag < 0:
                    threshold = -1 * threshold_flag * default_threshold
                    log.info("Background threshold set to {} based on {}".format(threshold.max(), default_threshold.max()))
                    bkg_rms_mean = threshold.max()
                else:
                    bkg_rms_mean = 3. * threshold_flag
                    threshold = bkg_rms_mean

                if bkg_rms_mean < 0:
                    bkg_rms_mean = 0.
                break

        # If Background2D does not work at all, define default scalar values for
        # the background to be used in source identification
        if bkg is None:
            bkg_mean = bkg_rms_mean = max(0.01, self.data.min())
            bkg_rms = nsigma * bkg_rms_mean
            bkg_dao_rms = bkg_rms_mean
            threshold = bkg_rms_mean + bkg_rms

        # *** FIX: Need to do something for bkg if bkg is None ***

        # Report other useful quantities
        log.info("")
        log.info("Mean background: {}".format(bkg_mean))
        log.info("Mean threshold: {}".format(np.mean(threshold)))
        log.info("")
        log.info("{}".format("=" * 80))

        self.bkg = bkg
        self.bkg_dao_rms = bkg_dao_rms
        self.bkg_rms_mean = bkg_rms_mean
        self.threshold = threshold

    def _get_header_data(self):
        """Read FITS keywords from the primary or extension header and store the
        information in a dictionary

        Returns
        -------
        keyword_dict : dictionary
            dictionary of keyword values
        """

        keyword_dict = {}

        keyword_dict["proposal_id"] = self.imghdu[0].header["PROPOSID"]
        keyword_dict["image_file_name"] = self.imghdu[0].header['FILENAME'].upper()
        keyword_dict["target_name"] = self.imghdu[0].header["TARGNAME"].upper()
        keyword_dict["date_obs"] = self.imghdu[0].header["DATE-OBS"]
        keyword_dict["instrument"] = self.imghdu[0].header["INSTRUME"].upper()
        keyword_dict["detector"] = self.imghdu[0].header["DETECTOR"].upper()
        keyword_dict["target_ra"] = self.imghdu[0].header["RA_TARG"]
        keyword_dict["target_dec"] = self.imghdu[0].header["DEC_TARG"]
        keyword_dict["expo_start"] = self.imghdu[0].header["EXPSTART"]
        keyword_dict["texpo_time"] = self.imghdu[0].header["TEXPTIME"]
        keyword_dict["ccd_gain"] = self.imghdu[0].header["CCDGAIN"]
        keyword_dict["aperture_pa"] = self.imghdu[0].header["PA_V3"]

        # The total detection product has the FILTER keyword in
        # the primary header - read it for any instrument.
        #
        # For the filter detection product:
        # WFC3 only has FILTER, but ACS has FILTER1 and FILTER2
        # in the primary header.
        if self.ghd_product.lower() == "tdp":
            keyword_dict["filter"] = self.imghdu[0].header["FILTER"]
        # The filter detection product...
        else:
            if keyword_dict["instrument"] == "ACS":
                keyword_dict["filter1"] = self.imghdu[0].header["FILTER1"]
                keyword_dict["filter2"] = self.imghdu[0].header["FILTER2"]
            else:
                keyword_dict["filter1"] = self.imghdu[0].header["FILTER"]
                keyword_dict["filter2"] = ""

        # Get the HSTWCS object from the first extension
        keyword_dict["wcs_name"] = self.imghdu[1].header["WCSNAME"]
        keyword_dict["wcs_type"] = self.imghdu[1].header["WCSTYPE"]
        log.info('WCSTYPE: {}'.format(keyword_dict["wcs_type"]))
        keyword_dict["orientation"] = self.imghdu[1].header["ORIENTAT"]
        keyword_dict["aperture_ra"] = self.imghdu[1].header["RA_APER"]
        keyword_dict["aperture_dec"] = self.imghdu[1].header["DEC_APER"]

        return keyword_dict


class HAPCatalogs:
    """Generate photometric sourcelist for specified TOTAL or FILTER product image.
    """

    def __init__(self, fitsfile, debug=False, types=None, tp_sources=None):
        self.label = "HAPCatalogs"
        self.description = "A class used to generate photometric sourcelists using aperture photometry"

        self.imgname = fitsfile
        self.debug = debug
        self.tp_soruces = tp_sources  # <---total product catalogs.catalogs[*].sources

        # Determine what types of catalogs have been requested
        if not isinstance(types, list) and types in [None, 'both']:
            types = CATALOG_TYPES

        elif types == 'aperture' or types == 'segment':
            types = [types]
        else:
            if any([t not in CATALOG_TYPES for t in types]):
                log.error("Catalog types {} not supported. Only {} are valid.".format(types, CATALOG_TYPES))
                raise ValueError

        self.types = types

        # Parameter dictionary definition
        self.instrument = self.imgname.split("_")[3].upper()
        self.detector = self.imgname.split("_")[4].upper()
        self.inst_det = "{} {}".format(self.instrument, self.detector)
        self.full_param_dict = ParamDict()
        self.param_dict = self.full_param_dict.get_params(self.instrument, self.detector)

        # Compute the background for this image
        self.image = CatalogImage(fitsfile)
        self.image.compute_background(nsigma=self.param_dict['dao']['bthresh'],
                                      threshold_flag=self.param_dict['sourcex']['thresh'])  # TODO previoulsy, nsigma=self.param_dict['sourcex']['bthresh']

        self.image.build_kernel(self.param_dict['dao']['TWEAK_FWHMPSF'],
                                self.param_dict['astrodrizzle']['SCALE'])

        # Initialize all catalog types here...
        # This does NOT identify or measure sources to create the catalogs at this point...
        # The syntax here is EXTREMELY cludgy, but until a more compact way to do this is found,
        #  it will have to do...
        self.catalogs = {}
        if 'aperture' in self.types:
            self.catalogs['aperture'] = HAPPointCatalog(self.image, self.param_dict, self.debug, tp_sources=tp_sources)
        if 'segment' in self.types:
            self.catalogs['segment'] = HAPSegmentCatalog(self.image, self.param_dict,
                                                         self.debug, tp_sources=tp_sources)

    def identify(self, **pars):
        """Build catalogs for this image.

        Parameters
        ----------
        types : list
            List of catalog types to be generated.  If None, build all available catalogs.
            Supported types of catalogs include: 'aperture', 'segment'.
        """
        # Support user-input value of 'None' which will trigger generation of all catalog types
        for catalog in self.catalogs:
            log.info("Identifying {} sources".format(catalog))
            self.catalogs[catalog].identify_sources(**pars)

    def measure(self, **pars):
        """Perform photometry and other measurements on sources for this image.

        Parameters
        ----------
        types : list
            List of catalog types to be generated.  If None, build all available catalogs.
            Supported types of catalogs include: 'aperture', 'segment'.
        """
        # Make sure we at least have a default 2D background computed
        for catalog in self.catalogs.values():
            if catalog.sources is None:
                catalog.identify_sources(**pars)

        for catalog in self.catalogs.values():
            catalog.measure_sources(**pars)

    def write(self, **pars):
        """Write catalogs for this image to output files.

        Parameters
        ----------
        types : list
            List of catalog types to be generated.  If None, build all available catalogs.
            Supported types of catalogs include: 'aperture', 'segment'.
        """
        # Make sure we at least have a default 2D background computed

        for catalog in self.catalogs.values():
            if catalog.source_cat is None:
                if hasattr(catalog, 'total_source_cat'):  # for total product segment processing
                    catalog.source_cat = catalog.total_source_cat  # TODO: find a less memory-intensive way to do this.
                else:
                    catalog.source_cat = catalog.sources  # for total product point-source processing
            catalog.write_catalog


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class HAPCatalogBase:
    """Virtual class used to define API for all catalogs"""
    catalog_suffix = ".ecsv"
    catalog_region_suffix = ".reg"
    catalog_format = "ascii.ecsv"

    def __init__(self, image, param_dict, debug, tp_sources):
        self.image = image
        self.imgname = image.imgname
        self.bkg = image.bkg
        self.param_dict = param_dict
        self.debug = debug

        self.sourcelist_filename = self.imgname.replace(self.imgname[-9:], self.catalog_suffix)

        # Initialize attributes which get computed by class methods
        self.bkg_used = None  # actual background used for source identification/measurement
        self.sources = None  # list of identified source positions
        self.source_cat = None  # catalog of sources and their properties
        self.tp_sources = tp_sources

    def identify_sources(self, **pars):
        pass

    def measure_sources(self, **pars):
        pass

    def write_catalog(self, **pars):
        pass


class HAPPointCatalog(HAPCatalogBase):
    """Generate photometric sourcelist(s) for specified image(s) using aperture photometry of point sources.
    """
    catalog_suffix = "_point-cat.ecsv"

    def __init__(self, image, param_dict, debug, tp_sources):
        super().__init__(image, param_dict, debug, tp_sources)

    def identify_sources(self, bkgsig_sf=4., dao_ratio=0.8, simple_bkg=False):
        """Create a master coordinate list of sources identified in the specified total detection product image

        Parameters
        ----------
        bkgsig_sf : float
            multiplictive scale factor applied to background sigma value to compute DAOfind input parameter
            'threshold'. Default value = 2.

        dao_ratio : float
            The ratio of the minor to major axis standard deviations of the Gaussian kernel.

        simple_bkg : bool, optional
            Should the input image will be background subtracted using pre-computed background?
            Default value is False.

        Returns
        -------
        sources : astropy table
            Table containing x, y coordinates of identified sources
        """
        # threshold = self.param_dict['dao']['TWEAK_THRESHOLD']

        # read in sci, wht extensions of drizzled product
        image = self.image.data.copy()

        # Estimate FWHM from image sources
        # Background statistics need to be computed prior to subtracting background from image
        bkg_sigma = mad_std(image, ignore_nan=True)
        detect_sources_thresh = bkgsig_sf * bkg_sigma

        # Input image will be background subtracted using pre-computed background, unless
        # specified explicitly by the user
        if simple_bkg:
            self.bkg_used = np.nanmedian(image)
            image -= self.bkg_used
        else:
        # Estimate background
        # self.compute_background(threshold)
            self.bkg_used = self.image.bkg.background
            image -= self.bkg_used

        segm = detect_sources(image, detect_sources_thresh, npixels=self.param_dict["sourcex"]["source_box"],
                              filter_kernel=self.image.kernel)
        cat = source_properties(image, segm)
        source_table = cat.to_table()
        smajor_sigma = source_table['semimajor_axis_sigma'].mean().value
        source_fwhm = smajor_sigma * gaussian_sigma_to_fwhm
        if not self.tp_sources:
            # Report configuration values to log
            log.info("{}".format("=" * 80))
            log.info("")
            log.info("Point-source finding settings")
            log.info("Total Detection Product - Input Parameters")
            log.info("INPUT PARAMETERS")
            log.info("{}: {}".format("bkgsig_sf", bkgsig_sf))
            log.info("{}: {}".format("dao_ratio", dao_ratio))
            log.info("{}: {}".format("simple_bkg", simple_bkg))
            log.info("{}: {}".format("self.image.bkg_rms_mean", self.image.bkg_rms_mean))
            log.info("{}: {}".format("self.image.bkg_rms_mean", self.image.bkg_rms_mean))
            log.info("{}: {}".format("self.param_dict['sourcex']['source_box']",
                                     self.param_dict["sourcex"]["source_box"]))
            log.info("\nDERIVED PARAMETERS")
            log.info("{}: {}".format("bkg_sigma", bkg_sigma))
            log.info("{}: {}".format("detect_sources_thresh", detect_sources_thresh))
            log.info("{}: {}".format("smajor_sigma", smajor_sigma))
            log.info("{}: {}".format("source_fwhm", source_fwhm))
            log.info("")
            log.info("{}".format("=" * 80))

            # find ALL the sources!!!
            log.info("DAOStarFinder(fwhm={}, threshold={}, ratio={})".format(source_fwhm,
                                                                             self.image.bkg_rms_mean, dao_ratio))
            daofind = DAOStarFinder(fwhm=source_fwhm, threshold=self.image.bkg_rms_mean, ratio=dao_ratio)

            # create mask to reject any sources located less than 10 pixels from a image/chip edge
            wht_image = self.image.data.copy()
            binary_inverted_wht = np.where(wht_image == 0, 1, 0)
            exclusion_mask = ndimage.binary_dilation(binary_inverted_wht, iterations=10)

            sources = daofind(image, mask=exclusion_mask)

            for col in sources.colnames:
                sources[col].info.format = '%.8g'  # for consistent table output

            self.sources = sources

        # if processing filter product, use sources identified by parent total drizzle product identify_sources() run
        if self.tp_sources:
            self.sources = self.tp_sources['aperture']['sources']

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def measure_sources(self, aper_radius=4.):
        """Perform aperture photometry on identified sources

        Parameters
        ----------
        sources : astropy table
            Table containing x, y coordinates of identified sources

        aper_radius : float or list of floats
            Aperture radius (in pixels) used for photometry. Default value = 4.

        Returns
        -------
        phot_table : astropy table
            Table containing photometric information for specified sources based on image data in the specified image.
        """
        log.info("Performing aperture photometry on identified point-sources")
        # Open and background subtract image
        image = self.image.data.copy()
        image -= self.bkg_used

        # # Aperture Photometry
        # positions = (self.sources['xcentroid'], self.sources['ycentroid'])
        # apertures = CircularAperture(positions, r=aper_radius)
        # phot_table = aperture_photometry(image, apertures)
        #
        # for col in phot_table.colnames: phot_table[col].info.format = '%.8g'  # for consistent table output
        #
        # self.source_cat = phot_table

        # ADAPTION OF HLA CLASSIC CODE 'HLA_SOURCELIST' SUBROUTINE 'DAOPHOT_STYLE_PHOTOMETRY' LINE 1019
        # +++++++++++++++++++ Hardwired presets just to get things moving  +++++++++++++++++++
        # TODO: Remove. All these values should come from static values in config files or be determined dynamically
        platescale = self.param_dict['astrodrizzle']['SCALE']  # arcsec/pixel
        skyannulus_arcsec = 0.25
        skyannulus_pix = skyannulus_arcsec/platescale
        dskyannulus_arcsec = 0.25
        dskyannulus_pix = dskyannulus_arcsec/platescale
        salgorithm = 'mode'
        # +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
        # Compute AB mag zeropoint.
        photplam = self.image.imghdu[1].header['photplam']
        photflam = self.image.imghdu[1].header['photflam']
        ab_zeropoint = -2.5 * np.log10(photflam) - 21.10 - 5.0 * np.log10(photplam) + 18.6921

        # Compute average gain
        gain = self.image.imghdu[0].header['exptime'] * np.mean([self.image.imghdu[0].header['atodgna'],
                                                                 self.image.imghdu[0].header['atodgnb'],
                                                                 self.image.imghdu[0].header['atodgnc'],
                                                                 self.image.imghdu[0].header['atodgnd']])

        # load in coords of sources identified in total product
        positions = (self.sources['xcentroid'], self.sources['ycentroid'])

        # adjust coods for calculations that assume origin value of 0, rather than 1.
        pos_x = np.asarray(positions[0])
        pos_y = np.asarray(positions[1])

        # define list of background annulii
        bg_apers = CircularAnnulus((pos_x, pos_y), r_in=skyannulus_arcsec, r_out=skyannulus_arcsec + dskyannulus_arcsec)

        # convert photometric aperture radii from arcsec to pixels and create list of photometric apertures to measure
        aper_radius_arcsec = [self.param_dict['dao']['aperture_1'], self.param_dict['dao']['aperture_2']]
        aper_radius_list_pixels = []
        for aper_radius in aper_radius_arcsec:
            aper_radius_list_pixels.append(aper_radius/platescale)
        phot_apers = [CircularAperture((pos_x, pos_y), r=r) for r in aper_radius_list_pixels]

        # parameter log dump!
        log.info("{}".format("=" * 80))
        log.info("")
        log.info("SUMMARY OF INPUT PARAMETERS")
        log.info("self.imgname:   {}".format(self.imgname))
        log.info("platescale:       {}".format(platescale))
        log.info("radii (pixels):   {}".format(aper_radius_list_pixels))
        log.info("radii (arcsec):   {}".format(aper_radius_arcsec))
        log.info("annulus:          {}".format(skyannulus_arcsec))
        log.info("dSkyAnnulus:      {}".format(dskyannulus_arcsec))
        log.info("salgorithm:       {}".format(salgorithm))
        log.info("gain:             {}".format(gain))
        log.info("ab_zeropoint:     {}".format(ab_zeropoint))
        log.info(" ")
        log.info("{}".format("=" * 80))
        log.info("")

        # Perform aperture photometry
        photometry_tbl = photometry_tools.iraf_style_photometry(phot_apers, bg_apers, data=image, platescale=platescale,
                                                                error_array=self.bkg.background_rms,
                                                                bg_method=salgorithm, epadu=gain,
                                                                zero_point=ab_zeropoint)

        # convert coords back to origin value = 1 rather than 0
        photometry_tbl["XCENTER"] = photometry_tbl["XCENTER"] + 1.
        photometry_tbl["YCENTER"] = photometry_tbl["YCENTER"] + 1.

        # calculate and add RA and DEC columns to table
        ra, dec = self.transform_list_xy_to_ra_dec(photometry_tbl["XCENTER"], photometry_tbl["YCENTER"], self.imgname)  # TODO: replace with all_pix2sky or somthing at a later date
        ra_col = Column(name="RA", data=ra, dtype=np.float64)
        dec_col = Column(name="DEC", data=dec, dtype=np.float64)
        photometry_tbl.add_column(ra_col, index=2)
        photometry_tbl.add_column(dec_col, index=3)

        # Calculate and add concentration index (CI) column to table
        ci_data = photometry_tbl["MAG_{}".format(aper_radius_arcsec[0])].data - photometry_tbl[
            "MAG_{}".format(aper_radius_arcsec[1])].data
        ci_mask = np.logical_and(np.abs(ci_data) > 0.0, np.abs(ci_data) < 1.0e-30)
        big_bad_index = np.where(abs(ci_data) > 1.0e20)
        ci_mask[big_bad_index] = True
        ci_col = MaskedColumn(name="CI", data=ci_data, dtype=np.float64, mask=ci_mask)
        photometry_tbl.add_column(ci_col)

        # Add zero-value "Flags" column in preparation for source flagging
        flag_col = Column(name="Flags", data=np.zeros_like(photometry_tbl['ID']), dtype=np.int64)
        photometry_tbl.add_column(flag_col)

        # Add null-value "TotMag(<outer radiiArc>)" and "TotMag(<outer radiiArc>)" columns
        empty_tot_mag = MaskedColumn(name="TotMag({})".format(aper_radius_arcsec[1]), fill_value=None, mask=True,
                                     length=len(photometry_tbl["XCENTER"].data), dtype=np.int64)
        empty_tot_mag_err = MaskedColumn(name="TotMagErr({})".format(aper_radius_arcsec[1]), fill_value=None, mask=True,
                                         length=len(photometry_tbl["XCENTER"].data), dtype=np.int64)
        photometry_tbl.add_column(empty_tot_mag)
        photometry_tbl.add_column(empty_tot_mag_err)

        # build final output table
        final_col_order = ["XCENTER", "YCENTER", "RA", "DEC", "ID", "MAG_{}".format(aper_radius_arcsec[0]),
                           "MAG_{}".format(aper_radius_arcsec[1]), "MERR_{}".format(aper_radius_arcsec[0]),
                           "MERR_{}".format(aper_radius_arcsec[1]), "MSKY", "STDEV",
                           "FLUX_{}".format(aper_radius_arcsec[1]), "TotMag({})".format(aper_radius_arcsec[1]),
                           "TotMagErr({})".format(aper_radius_arcsec[1]), "CI", "Flags"]
        output_photometry_table = photometry_tbl[final_col_order]

        # format output table columns
        final_col_format = {"RA": "13.10f", "DEC": "13.10f", "MAG_{}".format(aper_radius_arcsec[0]): '6.3f',
                            "MAG_{}".format(aper_radius_arcsec[1]): '6.3f',
                            "MERR_{}".format(aper_radius_arcsec[0]): '6.3f',
                            "MERR_{}".format(aper_radius_arcsec[1]): '6.3f', "MSKY": '10.8f', "STDEV": '10.8f',
                            "FLUX_{}".format(aper_radius_arcsec[1]): '10.8f', "CI": "7.3f"}
        for fcf_key in final_col_format.keys():
            output_photometry_table[fcf_key].format = final_col_format[fcf_key]

        # change some column titles to match old daophot.txt files
        rename_dict = {"XCENTER": "X-Center", "YCENTER": "Y-Center",
                       "MAG_{}".format(aper_radius_arcsec[0]): "MagAp({})".format(aper_radius_arcsec[0]),
                       "MAG_{}".format(aper_radius_arcsec[1]): "MagAp({})".format(aper_radius_arcsec[1]),
                       "MERR_{}".format(aper_radius_arcsec[0]): "MagErr({})".format(aper_radius_arcsec[0]),
                       "MERR_{}".format(aper_radius_arcsec[1]): "MagErr({})".format(aper_radius_arcsec[1]),
                       "MSKY": "MSky({})".format(aper_radius_arcsec[1]),
                       "STDEV": "Stdev({})".format(aper_radius_arcsec[1]),
                       "FLUX_{}".format(aper_radius_arcsec[1]): "Flux({})".format(aper_radius_arcsec[1])}
        for old_col_title in rename_dict:
            output_photometry_table.rename_column(old_col_title, rename_dict[old_col_title])
            log.info("Column '{}' renamed '{}'".format(old_col_title, rename_dict[old_col_title]))

        self.source_cat = output_photometry_table

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    @property
    def write_catalog(self):
        """Write specified catalog to file on disk

        Parameters
        ----------
        write_region_file : Boolean
           Write ds9-compatible region file along with the catalog file? Default value = False

        Returns
        -------
        Nothing!

        """
        # Write out catalog to ecsv file
        self.source_cat.write(self.sourcelist_filename, format=self.catalog_format)
        log.info("Wrote catalog file '{}' containing {} sources".format(self.sourcelist_filename, len(self.source_cat)))

        # Write out region file if input 'write_region_file' is turned on.
        if self.debug:
            out_table = self.source_cat.copy()
            if 'xcentroid' in out_table.keys():  # for point-source source catalogs
                # Remove all other columns besides xcentroid and ycentroid
                out_table.keep_columns(['xcentroid', 'ycentroid'])
                # Add offset of 1.0 in X and Y to line up sources in region file with image displayed in ds9.
                out_table['xcentroid'].data[:] += np.float64(1.0)
                out_table['ycentroid'].data[:] += np.float64(1.0)
            elif 'X-Center' in out_table.keys():  # for aperture photometric catalogs
                # Remove all other columns besides 'X-Center and Y-Center
                out_table.keep_columns(['X-Center', 'Y-Center'])
                # Add offset of 1.0 in X and Y to line up sources in region file with image displayed in ds9.
                out_table['X-Center'].data[:] += np.float64(1.0)
                out_table['Y-Center'].data[:] += np.float64(1.0)
            else:  # Bail out if anything else is encountered.
                log.info("Error: unrecognized catalog format. Skipping region file generation.")
                return()
            reg_filename = self.sourcelist_filename.replace("."+self.catalog_suffix.split(".")[1],
                                                            self.catalog_region_suffix)
            out_table.write(reg_filename, format="ascii")
            log.info("Wrote region file '{}' containing {} sources".format(reg_filename, len(out_table)))

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def transform_list_xy_to_ra_dec(self, list_of_x, list_of_y, drizzled_image):
        """Transform lists of X and Y coordinates to lists of RA and Dec coordinates
        This is a temporary solution until somthing like pix2sky or pix2world can be implemented in measure_sources.

        directly lifted from hla classic subroutine hla_sorucelist.Transform_list_xy_to_RA_Dec()

        Tested.

        Parameters
        ----------
        list_of_x : list
            list of x coordinates to convert

        list_of_y :
            list of y coordinates to convert

        drizzled_image : str
            Name of the image that corresponds to the table from DAOPhot. This image is used to re-write x and y
            coordinates in RA and Dec.

        Returns
        -------
        ra: list
            list of right ascension values

        dec : list
            list of declination values
        """
        import stwcs

        wcs1_drz = stwcs.wcsutil.HSTWCS(drizzled_image + "[1]")
        origin = 1
        # *origin* is the coordinate in the upper left corner of the
        # image.  In FITS and Fortran standards, this is 1.  In Numpy and C
        # standards this is 0.
        try:
            skyposish = wcs1_drz.all_pix2sky(list_of_x, list_of_y, origin)
        except AttributeError:
            skyposish = wcs1_drz.all_pix2world(list_of_x, list_of_y, origin)
        ra = skyposish[0]
        dec = skyposish[1]

        return ra, dec


# ----------------------------------------------------------------------------------------------------------------------
class HAPSegmentCatalog(HAPCatalogBase):
    """Generate photometric sourcelist(s) for specified image(s) using segment mapping.
    """
    catalog_suffix = "_segment-cat.ecsv"

    def __init__(self, image, param_dict, debug, tp_sources):
        super().__init__(image, param_dict, debug, tp_sources)

        # Get the instrument/detector-specific values from the self.param_dict
        self.fwhm = self.param_dict["sourcex"]["fwhm"]
        self.size_source_box = self.param_dict["sourcex"]["source_box"]
        self.threshold_flag = self.param_dict["sourcex"]["thresh"]

    def identify_sources(self):
        """Use photutils to find sources in image based on segmentation.

        Parameters
        ----------
        se_debug : bool, optional
            Specify whether or not to plot the image and segmentation image for
            visualization and debugging purposes

        Returns
        -------
        segm : `photutils.segmentation.SegmentationImage`
            Two-dimensional segmentation image where found source regions are labeled with
            unique, non-zero positive integers.

        kernel :

        bkg : `~photutils.background.Background2D` or None
            A background map based upon the `~photutils.background.SExtractorBackground`
            estimator

        bkg_rms_mean : float
            Mean bkg.background FIX

        """
        # TODO: Finish up and optimize HAPSegmentCatalog.identify_sources()
        # Report configuration values to log
        log.info("{}".format("=" * 80))
        log.info("")
        log.info("SExtractor-like source finding settings for Photutils segmentation")
        log.info("Total Detection Product - Input Parameters")
        log.info("FWHM: {}".format(self.fwhm))
        log.info("size_source_box: {}".format(self.size_source_box))
        log.info("threshold: {}".format(np.mean(self.image.threshold)))
        log.info("")
        log.info("{}".format("=" * 80))

        # get the SCI image data
        imgarr = self.image.data.copy()

        #
        # Consider whether the auto-generated kernel (self.image.kernel) would work instead
        #
        # Only use a single kernel for now
        kernel_list = [Gaussian2DKernel, MexicanHat2DKernel]
        kernel_in_use = kernel_list[0]

        bkg = self.image.bkg
        threshold = self.image.threshold

        # FIX imgarr should be background subtracted, sextractor uses the filtered_data image
        imgarr_bkgsub = imgarr - bkg.background

        # *** FIX: should size_source_box size be used in all these places? ***
        # Create a 2D filter kernel - this will be used to smooth the input
        # image prior to thresholding in detect_sources().
        sigma = self.fwhm * gaussian_fwhm_to_sigma
        kernel = kernel_in_use(sigma, x_size=self.size_source_box, y_size=self.size_source_box)
        kernel.normalize()
        if not self.tp_sources:
            # Source segmentation/extraction
            # If the threshold includes the background level, then the input image
            # should NOT be background subtracted.
            # Note: SExtractor has "connectivity=8" which is the default for this function
            self.sources = detect_sources(imgarr, threshold, npixels=self.size_source_box, filter_kernel=kernel)
            self.kernel = kernel  # for use in measure_sources()
            self.total_source_cat = source_properties(imgarr_bkgsub, self.sources, background=bkg.background,
                                                      filter_kernel=kernel, wcs=self.image.imgwcs)

        # if processing filter product, use sources identified by parent total drizzle product identify_sources() run
        if self.tp_sources:
            self.sources = self.tp_sources['segment']['sources']
            self.kernel = self.tp_sources['segment']['kernel']

        # For debugging purposes...
        if self.debug:
            # Write out a catalog which can be used as an overlay for image in ds9
            if not hasattr(self, 'total_source_cat'):
                cat = source_properties(imgarr_bkgsub, self.sources, background=bkg.background, filter_kernel=kernel,
                                        wcs=self.image.imgwcs)
                table = cat.to_table()
            else:
                table = self.total_source_cat.to_table()

            # Copy out only the X and Y coordinates to a "debug table" and
            # cast as an Astropy Table
            tbl = Table(table["xcentroid", "ycentroid"])

            # Construct the debug output filename and write the catalog
            indx = self.sourcelist_filename.find("ecsv")
            outname = self.sourcelist_filename[0:indx] + "reg"

            tbl["xcentroid"].info.format = ".10f"  # optional format
            tbl["ycentroid"].info.format = ".10f"

            # Add one to the X and Y table values to put the data onto a one-based system,
            # particularly for display with DS9
            tbl["xcentroid"] = tbl["xcentroid"] + 1
            tbl["ycentroid"] = tbl["ycentroid"] + 1
            tbl.write(outname, format="ascii.commented_header")
            log.info("Wrote debug source catalog: {}".format(outname))

            """
            # Generate a graphic of the image and the segmented image
            norm = ImageNormalize(stretch=SqrtStretch())
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 12.5))
            ax1.imshow(imgarr, origin="lower", cmap="Greys_r", norm=norm)
            ax1.set_title("Data")
            ax2.imshow(segm, origin="lower", cmap=segm.cmap(random_state=12345))
            ax2.set_title("Segmentation Image")
            plt.show()
            """

        # TROUBLESOME at this time
        # Deblending is a combination of multi-thresholding and watershed
        # segmentation. Sextractor uses a multi-thresholding technique.
        # npixels = number of connected pixels in source
        # npixels and filter_kernel should match those used by detect_sources()
        # Note: SExtractor has "connectivity=8" which is the default for this function
        """
        segm = deblend_sources(imgarr, self.sources, npixels=size_source_box,
                               filter_kernel=kernel, nlevels=32,
                               contrast=0.005)
        print("after deblend. ", segm)
        """

        """
        if se_debug:
            # Generate a graphic of the image and the segmented image
            norm = ImageNormalize(stretch=SqrtStretch())
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 12.5))
            ax1.imshow(imgarr, origin="lower", cmap="Greys_r", norm=norm)
            ax1.set_title("Data")
            ax2.imshow(segm, origin="lower", cmap=segm.cmap(random_state=12345))
            ax2.set_title("Segmentation Image")
            plt.show()
        """

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def measure_sources(self):
        """Use the positions of the sources identified in the white light image to
        measure properties of these sources in the filter images

        An instrument/detector combination may have multiple filter-level products.
        This routine is called for each filter image which is then measured to generate
        a filter-level source catalog based on object positions measured in the total
        detection product image.

        Parameters
        ----------
        segm : `~astropy.photutils.segmentation` Segmentation image
            Two-dimensional image of labeled source regions based on the "white light" drizzed product

        kernel : `~astropy.convolution`
            Two dimensional function of a specified FWHM used to smooth the image and
            used in the detection of sources as well as for the determination of the
            source properties (this routine)

        catalog_filename : string
            Name of the output source catalog for the filter detection product

        Returns
        -------

        """
        # TODO: Finish up and optimize HAPSegmentCatalog.measure_sources()

        # get filter-level science data
        imgarr = self.image.data.copy()

        # Report configuration values to log
        log.info("{}".format("=" * 80))
        log.info("")
        log.info("SExtractor-like source property measurements based on Photutils segmentation")
        log.info("Filter Level Product - Input Parameters")
        log.info("FWHM: {}".format(self.fwhm))
        log.info("size_source_box: {}".format(self.size_source_box))
        log.info("")
        log.info("{}".format("=" * 80))

        # The data needs to be background subtracted when computing the source properties
        bkg = self.image.bkg

        imgarr_bkgsub = imgarr - bkg.background

        # Compute source properties...
        self.source_cat = source_properties(imgarr_bkgsub, self.sources, background=bkg.background,
                                            filter_kernel=self.kernel, wcs=self.image.imgwcs)
        log.info("Found {} sources from segmentation map".format(len(self.source_cat)))

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    @property
    def write_catalog(self):
        """Actually write the specified source catalog out to disk

        Parameters
        ----------
        seg_cat : list of `~photutils.SourceProperties` objects
            List of SourceProperties objects, one for each source found in the
            specified detection product

        product : str, optional
            Identification string for the catalog product being written.  This
            controls the data being put into the catalog product
        """
        # Convert the list of SourceProperties objects to a QTable and
        # document in column metadata Photutils columns which map to SExtractor columns
        seg_table = Table(self.source_cat.to_table())
        radec_data = seg_table["sky_centroid_icrs"]
        ra_icrs = radec_data.ra.degree
        dec_icrs = radec_data.dec.degree

        num_sources = len(seg_table)

        # If the output is for the total detection product, then only
        # a subset of the full catalog is needed.
        if self.image.ghd_product.lower() == "tdp":

            # [x|y]centroid are in pixels, physical data coordinates
            seg_subset_table = seg_table["xcentroid", "ycentroid"]

            # Add metadata to the output subset table
            seg_subset_table = self._annotate_table(seg_subset_table, num_sources,
                                                    product=self.image.ghd_product)

            seg_subset_table["xcentroid"].description = "SExtractor Column x_image"
            seg_subset_table["ycentroid"].description = "SExtractor Column y_image"
            seg_subset_table["RA_icrs"] = ra_icrs
            seg_subset_table["Dec_icrs"] = dec_icrs
            seg_subset_table["RA_icrs"].description = "SExtractor Column RA"
            seg_subset_table["Dec_icrs"].description = "SExtractor Column Dec"
            seg_subset_table["RA_icrs"].unit = u.deg
            seg_subset_table["Dec_icrs"].unit = u.deg

            # Write out the official total detection product source catalog
            seg_subset_table["xcentroid"].info.format = ".10f"
            seg_subset_table["ycentroid"].info.format = ".10f"
            seg_subset_table["RA_icrs"].info.format = ".10f"
            seg_subset_table["Dec_icrs"].info.format = ".10f"
            log.info("seg_subset_table (white light image): {}".format(seg_subset_table))

            seg_subset_table.write(self.sourcelist_filename, format=self.catalog_format)
            log.info("Wrote source catalog: {}".format(self.sourcelist_filename))

        # else the product is the "filter detection product"
        else:

            seg_table = self._annotate_table(seg_table, num_sources, product=self.image.ghd_product)

            # Rework the current table for output
            del seg_table["id"]
            del seg_table["sky_centroid"]
            del seg_table["sky_centroid_icrs"]
            rr = Column(ra_icrs, name="RA_icrs", description="SExtractor Column RA", unit=u.deg)
            dd = Column(dec_icrs, name="Dec_icrs", description="SExtractor Column Dec", unit=u.deg)
            log.info("Added RA_icrs, Dec_icrs columns to Segment catalog")
            seg_table.add_columns([dd, rr], indexes=[2, 3])

            # Add a description for columns which map to SExtractor catalog columns
            seg_table["xcentroid"].description = "SExtractor Column x_image"
            seg_table["ycentroid"].description = "SExtractor Column y_image"
            seg_table["background_at_centroid"].description = "SExtractor Column background"
            seg_table["source_sum"].description = "SExtractor Column flux_iso"
            seg_table["source_sum_err"].description = "SExtractor Column fluxerr_iso"
            # FIX: is mapping to _image or _world?  _image
            seg_table["cxx"].description = "SExtractor Column cxx_image, ellipse parameter"
            seg_table["cyy"].description = "SExtractor Column cyy_image, ellipse parameter"
            seg_table["cxy"].description = "SExtractor Column cxy_image, ellipse parameter"
            # FIX: is the mapping to _image or _world?
            seg_table["covar_sigx2"].description = "SExtractor Column x2_image, (0,0) element of covariance matrix"
            seg_table["covar_sigy2"].description = "SExtractor Column y2_image, (1,1) element of covariance matrix"
            seg_table[
                "covar_sigxy"].description = "SExtractor Column xy_image, (0,1) and (1,0) elements of covariance matrix"

            xmin_cols_orig = ['xmin', 'xmax', 'ymin', 'ymax']
            xmin_descr = "SExtractor Column {}_image"
            if xmin_cols_orig[0] not in seg_table.colnames:
                xmin_cols = ['bbox_{}'.format(cname) for cname in xmin_cols_orig]
            else:
                xmin_cols = xmin_cols_orig

            for cname, oname in zip(xmin_cols, xmin_cols_orig):
                seg_table[cname].description = xmin_descr.format(oname)

            # Write out the official filter detection product source catalog
            seg_table["xcentroid"].info.format = ".10f"
            seg_table["ycentroid"].info.format = ".10f"
            seg_table["RA_icrs"].info.format = ".10f"
            seg_table["Dec_icrs"].info.format = ".10f"
            log.info("seg_table (filter): {}".format(seg_table))

            seg_table.write(self.sourcelist_filename, format=self.catalog_format)
            log.info("Wrote filter source catalog: {}".format(self.sourcelist_filename))

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def _annotate_table(self, data_table, num_sources, product="tdp"):
        """Add state metadata to the output source catalog

        Parameters
        ----------
        data_table : QTable
            Table of source properties

        num_sources : int
            Number of sources (items) in table

        product : str, optional
            Identification string for the catalog product being written.  This
            controls the data being put into the catalog product

        Returns
        -------
        data_table : QTable
            Table of source properties updatd to contain state metadata

        """

        data_table.meta["WCSNAME"] = self.image.keyword_dict["wcs_name"]
        data_table.meta["WCSTYPE"] = self.image.keyword_dict["wcs_type"]
        data_table.meta["Proposal ID"] = self.image.keyword_dict["proposal_id"]
        data_table.meta["Image File Name"] = self.image.keyword_dict['image_file_name']
        data_table.meta["Target Name"] = self.image.keyword_dict["target_name"]
        data_table.meta["Date Observed"] = self.image.keyword_dict["date_obs"]
        # FIX
        if product.lower() == "tdp":
            data_table.meta["Time Observed"] = " "
            data_table.meta["Filter"] = self.image.keyword_dict["filter"]
        else:
            data_table.meta["Time Observed"] = "FIX ME"
            data_table.meta["Filter 1"] = self.image.keyword_dict["filter1"]
            data_table.meta["Filter 2"] = self.image.keyword_dict["filter2"]
        data_table.meta["Instrument"] = self.image.keyword_dict["instrument"]
        data_table.meta["Detector"] = self.image.keyword_dict["detector"]
        data_table.meta["Target RA"] = self.image.keyword_dict["target_ra"]
        data_table.meta["Target DEC"] = self.image.keyword_dict["target_dec"]
        data_table.meta["Orientation"] = self.image.keyword_dict["orientation"]
        data_table.meta["Aperture RA"] = self.image.keyword_dict["aperture_ra"]
        data_table.meta["Aperture DEC"] = self.image.keyword_dict["aperture_dec"]
        data_table.meta["Aperture PA"] = self.image.keyword_dict["aperture_pa"]
        data_table.meta["Exposure Start"] = self.image.keyword_dict["expo_start"]
        data_table.meta["Total Exposure Time"] = self.image.keyword_dict["texpo_time"]
        data_table.meta["CCD Gain"] = self.image.keyword_dict["ccd_gain"]
        data_table.meta["Number of sources"] = num_sources
        data_table.meta[""] = " "
        data_table.meta[""] = "Absolute coordinates are in a zero-based coordinate system."

        return (data_table)


# ======================================================================================================================