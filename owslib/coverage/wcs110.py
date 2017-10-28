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

from .wcsBase import WCSBase, ServiceException, WCSCapabilitiesReader, getNamespaces
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
        self.ns = getNamespaces(xml)
        self.ns['wcs'] = 'http://www.opengis.net/wcs/1.1'
        self._capabilities = reader.readString(xml) if xml else reader.read(url)

        self.url = url
        self.cookies = cookies

        # check for exceptions
        se = self._capabilities.find('.//ows:Exception', self.ns)

        if se is not None:
            err_message = str(se.text).strip()
            raise ServiceException(err_message, xml)

        # serviceIdentification metadata
        elem = self._capabilities.find('ows:ServiceIdentification', self.ns)
        self.identification = ServiceIdentification(elem, self.ns)

        # serviceProvider
        elem = self._capabilities.find('ows:ServiceProvider', self.ns)
        self.provider = ServiceProvider(elem, self.ns)

        # serviceOperations
        self.operations = []
        for elem in self._capabilities.findall('ows:OperationsMetadata/ows:Operation', self.ns):
            self.operations.append(Operation(elem, self.ns))

        # serviceContents: our assumption is that services use a top-level layer
        # as a metadata organizer, nothing more.
        self.contents = {}
        top = self._capabilities.find('wcs:Contents/wcs:CoverageSummary', self.ns)
        for elem in self._capabilities.findall('wcs:Contents/wcs:CoverageSummary/wcs:CoverageSummary', self.ns):
            cm = ContentMetadata(elem, top, self, self.ns)
            self.contents[cm.id] = cm

        if self.contents == {}:
            # non-hierarchical.
            top = None
            for elem in self._capabilities.findall('wcs:Contents/wcs:CoverageSummary', self.ns):
                cm = ContentMetadata(elem, top, self, self.ns)
                # make the describeCoverage requests to populate the supported formats/crs attributes
                self.contents[cm.id] = cm

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


class Operation(object):
    """
    Abstraction for operation metadata
    Implements IOperationMetadata.
    """
    ns = Namespaces_1_1_0()

    def __init__(self, elem, nmSpc):
        self.name = elem.get('name')
        self.formatOptions = [f.text for f in elem.findall('ows:Parameter/ows:Value', nmSpc)]
        methods = []

        for verb in elem.findall('ows:DCP/ows:HTTP/ows:Get', nmSpc):
            url = verb.attrib['{{{}}}href'.format(nmSpc['xlink'])]
            methods.append((verb.tag, {'url': url}))
        self.methods = dict(methods)


class ServiceIdentification(object):
    """
    Abstraction for WCS ServiceIdentification Metadata
    implements IServiceIdentificationMetadata
    """

    def __init__(self, elem, nmSpc):
        self.service = 'WCS'

        self.title = elem.find('ows:Title', nmSpc)
        self.abstract = elem.find('ows:Abstract', nmSpc)
        self.keywords = [f.text for f in elem.findall('.//ows:Keyword', nmSpc)]
        attr = dict()
        attr['type'] = elem.find('ows:ServiceType', nmSpc)
        attr['version'] = elem.find('ows:ServiceTypeVersion', nmSpc)
        attr['fees'] = elem.find('ows:Fees', nmSpc)
        attr['accessConstraints'] = elem.find('ows:AccessConstraints', nmSpc)

        for key, val in attr.items():
            setattr(self, key, val)


class ServiceProvider(object):
    """
    Abstraction for WCS ServiceProvider Metadata
    implements IServiceProviderMetadata
    """

    def __init__(self, elem, nmSpc):
        name = elem.find('ows:ServiceProvider', nmSpc)

        self.name = name.text if name else None

        # self.contact=ServiceContact(elem.find(nmSpc.OWS('ServiceContact')))
        self.contact = ContactMetadata(elem, nmSpc)
        self.url = self.name  # no obvious definitive place for url in wcs, repeat provider name?


class ContactMetadata(object):
    """
    Abstraction for WCS ContactMetadata
    implements IContactMetadata
    """

    def __init__(self, elem, nmSpc):

        info = dict()

        info['name'] = elem.find('.//ows:ServiceContact/ows:IndividualName', nmSpc)
        info['organization'] = elem.find('.//ows:ProviderName', nmSpc)
        address = elem.find('.//ows:ServiceContact/ows:ContactInfo/ows:Address', nmSpc)
        info['address'] = address.find('ows:DeliveryPoint', nmSpc) if address else None
        info['city'] = address.find('ows:City', nmSpc) if address else None
        info['region'] = address.find('ows:AdministrativeArea', nmSpc) if address else None
        info['postcode'] = address.find('ows:PostalCode', nmSpc) if address else None
        info['country'] = address.find('ows:Country', nmSpc) if address else None
        info['email'] = address.find('ows:ElectronicMailAddress', nmSpc) if address else None

        for key, val in info.items():
                setattr(self, key, val.text)


class ContentMetadata(object):
    """
    Abstraction for WCS ContentMetadata
    Implements IContentMetadata
    """

    def __init__(self, elem, parent, service, nmSpc):
        """Initialize."""
        # TODO - examine the parent for bounding box info.

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
        b = elem.findall('ows:WGS84BoundingBox', nmSpc)
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
        self.supportedCRS = [Crs(x.text) for x in elem.findall('wcs:SupportedCRS', nmSpc)]

        # SupportedFormats
        self.supportedFormats = [x.text for x in elem.findall('wcs:SupportedFormat', nmSpc)]

    # grid is either a gml:Grid or a gml:RectifiedGrid if supplied as part of the DescribeCoverage response.
    def _getGrid(self):
        grid = None
        # TODO- convert this to 1.1 from 1.0
        # if not hasattr(self, 'descCov'):
        # self.descCov=self._service.getDescribeCoverage(self.id)
        # gridelem= self.descCov.find(ns('CoverageOffering/')+ns('domainSet/')+ns('spatialDomain/')+'{http://www.opengis.net/gml}RectifiedGrid')
        # if gridelem is not None:
        # grid=RectifiedGrid(gridelem)
        # else:
        # gridelem=self.descCov.find(ns('CoverageOffering/')+ns('domainSet/')+ns('spatialDomain/')+'{http://www.opengis.net/gml}Grid')
        # grid=Grid(gridelem)
        return grid

    grid = property(_getGrid, None)

    # time limits/postions require a describeCoverage request therefore only resolve when requested
    def _getTimeLimits(self):
        timelimits = []
        for elem in self._service.getDescribeCoverage(self.id).findall(
                                        ns('CoverageDescription/') + ns('Domain/') + ns('TemporalDomain/') + ns(
                        'TimePeriod/')):
            subelems = elem.getchildren()
            timelimits = [subelems[0].text, subelems[1].text]
        return timelimits

    timelimits = property(_getTimeLimits, None)

    # TODO timepositions property
    def _getTimePositions(self):
        return []

    timepositions = property(_getTimePositions, None)

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
