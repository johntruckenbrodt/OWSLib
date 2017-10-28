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

from __future__ import (absolute_import, division, print_function)

from owslib.coverage.wcsBase import WCSBase, ServiceException, WCSCapabilitiesReader, getNamespaces

try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode
from owslib.util import openURL, testXMLValue
from owslib.crs import Crs


import logging
from owslib.util import log


#  function to save writing out WCS namespace in full each time
def ns(tag):
    return '{http://www.opengis.net/wcs}' + tag


class WebCoverageService_1_0_0(WCSBase):
    """Abstraction for OGC Web Coverage Service (WCS), version 1.0.0
    Implements IWebCoverageService.
    """

    def __init__(self, url, xml, cookies):
        self.version = '1.0.0'
        self.url = url
        self.cookies = cookies

        reader = WCSCapabilitiesReader(self.version, cookies)

        if xml:
            self._capabilities = reader.readString(xml)
            self.ns = getNamespaces(xml)
        else:
            self._capabilities = reader.read(url)
            self.ns = getNamespaces(openURL(reader.capabilities_url(url), cookies=self.cookies).read())

        self.ns['wcs'] = 'http://www.opengis.net/wcs'

        # check for exceptions
        se = self._capabilities.find('ServiceException')

        if se is not None:
            err_message = str(se.text).strip()
            raise ServiceException(err_message, xml)

        # serviceIdentification metadata
        subelem = self._capabilities.find('wcs:Service', self.ns)
        self.identification = ServiceIdentification(subelem, self.ns)

        # serviceProvider metadata
        subelem = self._capabilities.find('wcs:Service/wcs:responsibleParty', self.ns)
        self.provider = ServiceProvider(subelem, self.ns)

        # serviceOperations metadata
        operations = self._capabilities.all('wcs:Capability/wcs:Request', self.ns)[:]
        self.operations = [OperationMetadata(x, self.ns) for x in operations]

        # serviceContents metadata
        self.contents = {}
        for elem in self._capabilities.findall('wcs:ContentMetadata/wcs:CoverageOfferingBrief', self.ns):
            cm = ContentMetadata(elem, self, self.ns)
            self.contents[cm.id] = cm

        # Some WCS servers (wrongly) advertise 'Content' OfferingBrief instead.
        if self.contents == {}:
            for elem in self._capabilities.findall('wcs:ContentMetadata/wcs:ContentOfferingBrief', self.ns):
                cm = ContentMetadata(elem, self, self.ns)
                self.contents[cm.id] = cm

        WCSBase.__init__(self)

    def __makeString(self, value):
        # using repr unconditionally breaks things in some circumstances if a value is already a string
        if type(value) is not str:
            sval = repr(value)
        else:
            sval = value
        return sval

    def getCoverage(self, identifier=None, bbox=None, time=None, format=None, crs=None, width=None, height=None,
                    resx=None, resy=None, resz=None, parameter=None, method='Get', **kwargs):
        """Request and return a coverage from the WCS as a file-like object
        note: additional **kwargs helps with multi-version implementation
        core keyword arguments should be supported cross version
        example:
        cvg=wcs.getCoverage(identifier=['TuMYrRQ4'], timeSequence=['2792-06-01T00:00:00.0'], bbox=(-112,36,-106,41),format='cf-netcdf')

        is equivalent to:
        http://myhost/mywcs?SERVICE=WCS&REQUEST=GetCoverage&IDENTIFIER=TuMYrRQ4&VERSION=1.1.0&BOUNDINGBOX=-180,-90,180,90&TIME=2792-06-01T00:00:00.0&FORMAT=cf-netcdf
           
        """
        if log.isEnabledFor(logging.DEBUG):
            log.debug(
                'WCS 1.0.0 DEBUG: Parameters passed to GetCoverage: identifier=%s, bbox=%s, time=%s, format=%s, crs=%s, width=%s, height=%s, resx=%s, resy=%s, resz=%s, parameter=%s, method=%s, other_arguments=%s' % (
                identifier, bbox, time, format, crs, width, height, resx, resy, resz, parameter, method, str(kwargs)))

        try:
            base_url = next((m.get('url') for m in self.getOperationByName('GetCoverage').methods if
                             m.get('type').lower() == method.lower()))
        except StopIteration:
            base_url = self.url

        if log.isEnabledFor(logging.DEBUG):
            log.debug('WCS 1.0.0 DEBUG: base url of server: %s' % base_url)

        # process kwargs
        request = {'version': self.version, 'request': 'GetCoverage', 'service': 'WCS'}
        assert len(identifier) > 0
        request['Coverage'] = identifier
        # request['identifier'] = ','.join(identifier)
        if bbox:
            request['BBox'] = ','.join([self.__makeString(x) for x in bbox])
        else:
            request['BBox'] = None
        if time:
            request['time'] = ','.join(time)
        if crs:
            request['crs'] = crs
        request['format'] = format
        if width:
            request['width'] = width
        if height:
            request['height'] = height
        if resx:
            request['resx'] = resx
        if resy:
            request['resy'] = resy
        if resz:
            request['resz'] = resz

        # anything else e.g. vendor specific parameters must go through kwargs
        if kwargs:
            for kw in kwargs:
                request[kw] = kwargs[kw]

        # encode and request
        data = urlencode(request)
        if log.isEnabledFor(logging.DEBUG):
            log.debug('WCS 1.0.0 DEBUG: Second part of URL: %s' % data)

        u = openURL(base_url, data, method, self.cookies)

        return u


class OperationMetadata(object):
    """Abstraction for WCS metadata.   
    Implements IMetadata.
    """

    def __init__(self, elem, nmSpc):
        """."""
        self.name = elem.tag.split('}')[1]

        # self.formatOptions = [f.text for f in elem.findall('{http://www.opengis.net/wcs/1.1/ows}Parameter/{http://www.opengis.net/wcs/1.1/ows}AllowedValues/{http://www.opengis.net/wcs/1.1/ows}Value')]
        self.methods = []
        for resource in elem.findall('wcs:DCPType/wcs:HTTP/wcs:Get/wcs:OnlineResource', nmSpc):
            url = resource.attrib['{http://www.w3.org/1999/xlink}href']
            self.methods.append({'type': 'Get', 'url': url})
        for resource in elem.findall('wcs:DCPType/wcs:HTTP/wcs:Post/wcs:OnlineResource', nmSpc):
            url = resource.attrib['{http://www.w3.org/1999/xlink}href']
            self.methods.append({'type': 'Post', 'url': url})


class ServiceIdentification(object):
    """ Abstraction for ServiceIdentification metadata """

    def __init__(self, elem, nmSpc):
        # properties              
        self.type = 'OGC:WCS'
        self.version = '1.0.0'
        self.service = testXMLValue(elem.find('wcs:name', nmSpc))
        self.abstract = testXMLValue(elem.find('description', nmSpc))
        self.title = testXMLValue(elem.find('label', nmSpc))
        self.keywords = [f.text for f in elem.findall('wcs:keywords/wcs:keyword', nmSpc)]
        # note: differs from 'rights' in interface
        self.fees = elem.find('wcs:fees', nmSpc).text
        self.accessConstraints = elem.find('wcs:accessConstraints', nmSpc).text


class ServiceProvider(object):
    """ Abstraction for WCS ResponsibleParty 
    Implements IServiceProvider"""

    def __init__(self, elem, nmSpc):
        # it's not uncommon for the service provider info to be missing
        # so handle case where None is passed in
        if elem is None:
            self.name = None
            self.url = None
            self.contact = None
        else:
            self.name = testXMLValue(elem.find('wcs:organisationName', nmSpc))
            self.url = self.name  # there is no definitive place for url  WCS, repeat organisationName
            self.contact = ContactMetadata(elem, nmSpc)


class ContactMetadata(object):
    """
    Abstraction for WCS ContactMetadata
    implements IContactMetadata
    """

    def __init__(self, elem, nmSpc):

        info = dict()

        info['name'] = elem.find('wcs:individualName', nmSpc)
        info['organization'] = elem.find('wcs:organisationName', nmSpc)
        info['address'] = elem.find('wcs:contactInfo/wcs:address/wcs:deliveryPoint', nmSpc)
        info['city'] = elem.find('wcs:contactInfo/wcs:address/wcs:city', nmSpc)
        info['region'] = elem.find('wcs:contactInfo/wcs:address/wcs:administrativeArea', nmSpc)
        info['postcode'] = elem.find('wcs:contactInfo/wcs:address/wcs:postalCode', nmSpc)
        info['country'] = elem.find('wcs:contactInfo/wcs:address/wcs:country', nmSpc)
        info['email'] = elem.find('wcs:contactInfo/wcs:address/wcs:electronicMailAddress', nmSpc)

        for key, val in info.items():
                setattr(self, key, val.text)


class ContentMetadata(object):
    """
    Implements IContentMetadata
    """

    def __init__(self, elem, service, nmSpc):
        """Initialize. service is required so that describeCoverage requests may be made"""
        # TODO - examine the parent for bounding box info.

        self.ns = nmSpc

        # self._parent=parent
        self._elem = elem
        self._service = service
        self.id = elem.find('wcs:name', self.ns).text
        self.title = testXMLValue(elem.find('wcs:label', self.ns))
        self.abstract = testXMLValue(elem.find('wcs:description', self.ns))
        self.keywords = [f.text for f in elem.findall('wcs:keywords/wcs:keyword', self.ns)]
        self.boundingBox = None  # needed for iContentMetadata harmonisation
        self.boundingBoxWGS84 = None
        b = elem.find('wcs:lonLatEnvelope', self.ns)
        if b is not None:
            gmlpositions = b.findall('gml:pos', self.ns)
            lc = gmlpositions[0].text.split()
            uc = gmlpositions[1].text.split()
            self.boundingBoxWGS84 = tuple(map(float, lc + uc))

        # others not used but needed for iContentMetadata harmonisation
        self.styles = None
        self.crsOptions = None
        self.defaulttimeposition = None

    # grid is either a gml:Grid or a gml:RectifiedGrid if supplied as part of the DescribeCoverage response.
    def _getGrid(self):
        if not hasattr(self, 'descCov'):
            self.descCov = self._service.getDescribeCoverage(self.id)
        gridelem = self.descCov.find('wcs:CoverageOffering/wcs:domainSet/wcs:spatialDomain/gml:RectifiedGrid', self.ns)
        if gridelem is not None:
            grid = RectifiedGrid(gridelem, self.ns)
        else:
            gridelem = self.descCov.find('wcs:CoverageOffering/wcs:domainSet/wcs:spatialDomain/gml:Grid', self.ns)
            grid = Grid(gridelem, self.ns)
        return grid

    grid = property(_getGrid, None)

    # timelimits are the start/end times, timepositions are all timepoints. WCS servers can declare one or both or neither of these.
    def _getTimeLimits(self):
        timepoints, timelimits = [], []
        b = self._elem.find('wcs:lonLatEnvelope', self.ns)
        if b is not None:
            timepoints = b.findall('gml:timePosition', self.ns)
        else:
            # have to make a describeCoverage request...
            if not hasattr(self, 'descCov'):
                self.descCov = self._service.getDescribeCoverage(self.id)
            for pos in self.descCov.findall('wcs:CoverageOffering/wcs:domainSet/wcs:temporalDomain/gml:timePosition', self.ns):
                timepoints.append(pos)
        if timepoints:
            timelimits = [timepoints[0].text, timepoints[1].text]
        return timelimits

    timelimits = property(_getTimeLimits, None)

    def _getTimePositions(self):
        timepositions = []
        if not hasattr(self, 'descCov'):
            self.descCov = self._service.getDescribeCoverage(self.id)
        for pos in self.descCov.findall('wcs:CoverageOffering/wcs:domainSet/wcs:temporalDomain/gml:timePosition', self.ns):
            timepositions.append(pos.text)
        return timepositions

    timepositions = property(_getTimePositions, None)

    def _getOtherBoundingBoxes(self):
        """incomplete, should return other bounding boxes not in WGS84
            #TODO: find any other bounding boxes. Need to check for gml:EnvelopeWithTimePeriod."""

        bboxes = []

        if not hasattr(self, 'descCov'):
            self.descCov = self._service.getDescribeCoverage(self.id)

        for envelope in self.descCov.findall('wcs:CoverageOffering/wcs:domainSet/wcs:spatialDomain/gml:Envelope', self.ns):
            bbox = {}
            bbox['nativeSrs'] = envelope.attrib['srsName']
            gmlpositions = envelope.findall('{http://www.opengis.net/gml}pos')
            lc = gmlpositions[0].text.split()
            uc = gmlpositions[1].text.split()
            bbox['bbox'] = (
                float(lc[0]), float(lc[1]),
                float(uc[0]), float(uc[1])
            )
            bboxes.append(bbox)

        return bboxes

    boundingboxes = property(_getOtherBoundingBoxes, None)

    def _getSupportedCRSProperty(self):
        # gets supported crs info
        crss = []

        for crstype in ['response', 'requestResponse', 'native']:
            searchstring = 'wcs:CoverageOffering/wcs:supportedCRSs/wcs:{}CRSs'.format(crstype)
            for elem in self._service.getDescribeCoverage(self.id).findall(searchstring, self.ns):
                for crs in elem.text.split(' '):
                    crss.append(Crs(crs))
        return crss

    supportedCRS = property(_getSupportedCRSProperty, None)

    def _getSupportedFormatsProperty(self):
        # gets supported formats info
        frmts = []
        for elem in self._service.getDescribeCoverage(self.id).findall('wcs:CoverageOffering/wcs:supportedFormats/wcs:formats', self.ns):
            frmts.append(elem.text)
        return frmts

    supportedFormats = property(_getSupportedFormatsProperty, None)

    def _getAxisDescriptionsProperty(self):
        # gets any axis descriptions contained in the rangeset (requires a DescribeCoverage call to server).
        axisDescs = []
        for elem in self._service.getDescribeCoverage(self.id).findall('wcs:CoverageOffering/wcs:rangeSet/wcs:RangeSet/wcs:axisDescription/wcs:AxisDescription', self.ns):
            axisDescs.append(AxisDescription(elem))  # create a 'AxisDescription' object.
        return axisDescs

    axisDescriptions = property(_getAxisDescriptionsProperty, None)


# Adding classes to represent gml:grid and gml:rectifiedgrid. One of these is used for the cvg.grid property
# (where cvg is a member of the contents dictionary)
# There is no simple way to convert the offset values in a rectifiedgrid grid to real values without CRS understanding, therefore this is beyond the current scope of owslib, so the representation here is purely to provide access to the information in the GML.

class Grid(object):
    """
    Simple grid class to provide axis and value information for a gml grid
    """

    def __init__(self, grid, nmSpc):
        self.axislabels = []
        self.dimension = None
        self.lowlimits = []
        self.highlimits = []
        if grid is not None:
            self.dimension = int(grid.get('dimension'))
            self.lowlimits = grid.find('gml:limits/gml:GridEnvelope/gml:low', nmSpc).text.split(' ')
            self.highlimits = grid.find('gml:limits/gml:GridEnvelope/gml:high', nmSpc).text.split(' ')
            for axis in grid.findall('gml:axisName', nmSpc):
                self.axislabels.append(axis.text)


class RectifiedGrid(Grid):
    """
    RectifiedGrid class, extends Grid with additional offset vector information
    """

    def __init__(self, rectifiedgrid, nmSpc):
        super(RectifiedGrid, self).__init__(rectifiedgrid, nmSpc)
        self.origin = rectifiedgrid.find('gml:origin/gml:pos', nmSpc).text.split()
        self.offsetvectors = []
        for offset in rectifiedgrid.findall('gml:offsetVector', nmSpc):
            self.offsetvectors.append(offset.text.split())


class AxisDescription(object):
    """
    Class to represent the AxisDescription element optionally found as part of the RangeSet and used to
    define ordinates of additional dimensions such as wavelength bands or pressure levels
    """

    def __init__(self, axisdescElem):
        self.name = self.label = None
        self.values = []
        for elem in axisdescElem.getchildren():
            if elem.tag == ns('name'):
                self.name = elem.text
            elif elem.tag == ns('label'):
                self.label = elem.text
            elif elem.tag == ns('values'):
                for child in elem.getchildren():
                    self.values.append(child.text)
