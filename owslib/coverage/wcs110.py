# -*- coding: ISO-8859-15 -*-
# =============================================================================
# Copyright (c) 2004, 2006 Sean C. Gillies
# Copyright (c) 2007 STFC <http://www.stfc.ac.uk>
#
# Authors : 
#          Dominic Lowe <d.lowe@rl.ac.uk>
#
# Contact email: d.lowe@rl.ac.uk
# =============================================================================

# ########NOTE: Does not conform to new interfaces yet #################

from __future__ import (absolute_import, division, print_function)

from .wcsBase import WCSBase, ServiceException, WCSCapabilitiesReader, getNamespaces, ServiceIdentification, ServiceProvider, OperationMetadata, RectifiedGrid, Grid
from owslib.util import openURL

try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode

from owslib.crs import Crs

import logging
from owslib.util import log


class Namespaces_1_1_0():
    def WCS(self, tag):
        return '{http://www.opengis.net/wcs/1.1}' + tag

    def WCS_OWS(self, tag):
        return '{http://www.opengis.net/wcs/1.1/ows}' + tag

    def OWS(self, tag):
        return '{http://www.opengis.net/ows}' + tag


class WebCoverageService_1_1_0(WCSBase):
    """
    Abstraction for OGC Web Coverage Service (WCS), version 1.1.0
    Implements IWebCoverageService.
    """

    version = '1.1.0'
    # ns = Namespaces_1_1_0()

    def __init__(self, url, xml, cookies):
        # initialize from saved capability document or access the server
        reader = WCSCapabilitiesReader(self.version, cookies)

        if xml:
            self._capabilities = reader.readString(xml)
            self.ns = getNamespaces(xml)
        else:
            self._capabilities = reader.read(url)
            self.ns = getNamespaces(openURL(reader.capabilities_url(url), cookies=cookies).read())

        self.ns['wcs'] = 'http://www.opengis.net/wcs/1.1'

        if 'owcs' not in self.ns.keys():
            self.ns['owcs'] = self.ns['ows']

        self.url = url
        self.cookies = cookies

        # check for exceptions
        se = self._capabilities.find('.//ows:Exception', self.ns)

        if se is not None:
            err_message = str(se.text).strip()
            raise ServiceException(err_message, xml)

        # serviceIdentification metadata
        elem = self._capabilities.find('owcs:ServiceIdentification', self.ns)
        self.identification = ServiceIdentification(elem, self.ns, self.version)

        # serviceProvider
        elem = self._capabilities.find('ows:ServiceProvider', self.ns)
        self.provider = ServiceProvider(elem, self.ns, self.version)

        # serviceOperations
        self.operations = []
        for elem in self._capabilities.findall('owcs:OperationsMetadata/owcs:Operation', self.ns):
            self.operations.append(OperationMetadata(elem, self.ns, self.version))

        # serviceContents: different possibilities for top-level layer as a metadata organizer
        self.contents = {}
        for topid in ['wcs:Contents/wcs:CoverageSummary', 'wcs:Contents']:
            top = self._capabilities.find(topid, self.ns)
            cs = top.findall('wcs:CoverageSummary', self.ns)
            if len(cs) > 0:
                cm = [ContentMetadata(elem, top, self, self.ns, self.version) for elem in cs]
                self.contents = dict([(x.id, x) for x in cm])
                break

        WCSBase.__init__(self)

    # TO DO: Handle rest of the  WCS 1.1.0 keyword parameters e.g. GridCRS etc.
    def getCoverage(self, identifier=None, bbox=None, time=None, format=None, store=False, rangesubset=None,
                    gridbaseCRS=None, gridtype=None, gridCS=None, gridorigin=None, gridoffsets=None, method='Get',
                    **kwargs):
        """Request and return a coverage from the WCS as a file-like object
        note: additional **kwargs helps with multi-version implementation
        core keyword arguments should be supported cross version
        example:
        cvg=wcs.getCoverageRequest(identifier=['TuMYrRQ4'], time=['2792-06-01T00:00:00.0'], bbox=(-112,36,-106,41),format='application/netcdf', store='true')

        is equivalent to:
        http://myhost/mywcs?SERVICE=WCS&REQUEST=GetCoverage&IDENTIFIER=TuMYrRQ4&VERSION=1.1.0&BOUNDINGBOX=-180,-90,180,90&TIMESEQUENCE=2792-06-01T00:00:00.0&FORMAT=application/netcdf
        
        if store = true, returns a coverages XML file
        if store = false, returns a multipart mime
        """
        if log.isEnabledFor(logging.DEBUG):
            log.debug(
                'WCS 1.1.0 DEBUG: Parameters passed to GetCoverage: identifier=%s, bbox=%s, time=%s, format=%s, rangesubset=%s, gridbaseCRS=%s, gridtype=%s, gridCS=%s, gridorigin=%s, gridoffsets=%s, method=%s, other_arguments=%s' % (
                identifier, bbox, time, format, rangesubset, gridbaseCRS, gridtype, gridCS, gridorigin, gridoffsets,
                method, str(kwargs)))

        if method == 'Get':
            method = self.ns.WCS_OWS('Get')
        try:
            base_url = next((m.get('url') for m in self.getOperationByName('GetCoverage').methods if
                             m.get('type').lower() == method.lower()))
        except StopIteration:
            base_url = self.url

        # process kwargs
        request = {'version': self.version, 'request': 'GetCoverage', 'service': 'WCS'}
        assert len(identifier) > 0
        request['identifier'] = identifier
        # request['identifier'] = ','.join(identifier)
        if bbox:
            request['boundingbox'] = ','.join([repr(x) for x in bbox])
        if time:
            request['timesequence'] = ','.join(time)
        request['format'] = format
        request['store'] = store

        # rangesubset: untested - require a server implementation
        if rangesubset:
            request['RangeSubset'] = rangesubset

        # GridCRS structure: untested - require a server implementation
        if gridbaseCRS:
            request['gridbaseCRS'] = gridbaseCRS
        if gridtype:
            request['gridtype'] = gridtype
        if gridCS:
            request['gridCS'] = gridCS
        if gridorigin:
            request['gridorigin'] = gridorigin
        if gridoffsets:
            request['gridoffsets'] = gridoffsets

            # anything else e.g. vendor specific parameters must go through kwargs
        if kwargs:
            for kw in kwargs:
                request[kw] = kwargs[kw]

        # encode and request
        data = urlencode(request)

        u = openURL(base_url, data, method, self.cookies)
        return u


class ContentMetadata(object):
    """
    Abstraction for WCS ContentMetadata
    Implements IContentMetadata
    """

    def __init__(self, elem, parent, service, nmSpc, version):
        """Initialize."""
        # TODO - examine the parent for bounding box info.

        self.ns = nmSpc
        self.version = version
        self._service = service
        self._elem = elem
        self._parent = parent
        self.id = self._checkChildAndParent('.//wcs:Identifier', nmSpc)
        self.description = self._checkChildAndParent('.//wcs:Description', nmSpc)
        self.title = self._checkChildAndParent('.//ows:Title', nmSpc)
        self.abstract = self._checkChildAndParent('.//ows:Abstract', nmSpc)

        # keywords.
        self.keywords = [kw.text for kw in elem.findall('ows:Keywords/ows:Keyword', nmSpc)]

        # also inherit any keywords from parent coverage summary (if there is one)
        if parent is not None:
            keywords_parent = [kw.text for kw in parent.findall('ows:Keywords/ows:Keyword', nmSpc)]
            self.keywords += keywords_parent

        self.boundingBox = None  # needed for iContentMetadata harmonisation
        self.boundingBoxWGS84 = None
        b = elem.find('ows:WGS84BoundingBox', nmSpc)
        if b is not None:
            lc = b.find('ows:LowerCorner', nmSpc).text.split()
            uc = b.find('ows:UpperCorner', nmSpc).text.split()
            self.boundingBoxWGS84 = tuple(map(float, lc+uc))

        # bboxes - other CRS
        self.boundingboxes = []
        for bbox in elem.findall('ows:BoundingBox', nmSpc):
            try:
                lc = bbox.find('ows:LowerCorner', nmSpc).text.split()
                uc = bbox.find('ows:UpperCorner', nmSpc).text.split()
                crs = bbox.attrib['crs']
                boundingBox = tuple(map(float, lc+uc) + [crs])
                self.boundingboxes.append(boundingBox)
            except:
                pass

        # others not used but needed for iContentMetadata harmonisation
        self.styles = None
        self.crsOptions = None

        # SupportedCRS
        self.supportedCRS = [Crs(x.text) for x in elem.findall('.//wcs:SupportedCRS', nmSpc)]
        if len(self.supportedCRS) == 0:
            self.supportedCRS += [Crs(x.text) for x in parent.findall('wcs:SupportedCRS', nmSpc)]

        # SupportedFormats
        self.supportedFormats = [x.text for x in elem.findall('.//wcs:SupportedFormat', nmSpc)]
        if len(self.supportedFormats) == 0:
            self.supportedFormats += [x.text for x in parent.findall('wcs:SupportedFormat', nmSpc)]

    # grid is either a gml:Grid or a gml:RectifiedGrid if supplied as part of the DescribeCoverage response.
    @property
    def grid(self):
        if not hasattr(self, 'descCov'):
            self.descCov = self._service.getDescribeCoverage(self.id)
        gridelem = self.descCov.find('wcs:CoverageDescription/wcs:Domain/wcs:SpatialDomain', self.ns)

        if gridelem.find('wcs:GridCRS/wcs:GridOrigin', self.ns) is not None:
            grid = RectifiedGrid(gridelem, self.ns, self.version)
        else:
            grid = Grid(gridelem, self.ns, self.version)
        return grid

    # time limits/postions require a describeCoverage request therefore only resolve when requested
    @property
    def timelimits(self):
        timelimits = []
        for elem in self._service.getDescribeCoverage(self.id).findall(
                                        ns('CoverageDescription/') + ns('Domain/') + ns('TemporalDomain/') + ns(
                        'TimePeriod/')):
            subelems = elem.getchildren()
            timelimits = [subelems[0].text, subelems[1].text]
        return timelimits

    # TODO timepositions property
    @property
    def timepositions(self):
        return []

    def _checkChildAndParent(self, path, nmSpc):
        """
        checks child coverage  summary, and if item not found checks higher level coverage summary
        """
        try:
            value = self._elem.find(path, nmSpc).text
        except AttributeError:
            try:
                value = self._parent.find(path, nmSpc).text
            except AttributeError:
                value = None
        return value
