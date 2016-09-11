"""Exif GPS property

This program adds a property page to Nautilus allowing the end user to modify
GPS coordinates in image files. It uses OsmGpsMap and GExiv2 in order to
achieve this.
"""

from ConfigParser import ConfigParser
from re import search
from os.path import expanduser, join
from urllib import unquote
from gi import require_version
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject
from gi.repository import GExiv2, OsmGpsMap, Nautilus

require_version('Gtk', '3.0')
require_version('GExiv2', '0.10')
require_version('OsmGpsMap', '1.0')

GObject.threads_init()
Gdk.threads_init()
GObject.type_register(OsmGpsMap.Map)

def get_config(filename):
    """Returns the absolute path to the config file given its filename. This
    function does not ensure the file does exist.
    """
    return expanduser(join("~", ".config", filename))

class Configuration(object):
    """The Configuration class is an helper class dedicated to read and
    write configuration file for the ExifGpsEditor.

    At the moment, it gives only the previous_position attribute which
    contains a tuple of (latitude, longitude).
    """
    def __init__(self, filename):
        assert isinstance(filename, str)

        self._filename = get_config(filename)
        self._config = ConfigParser()

        self._config.set('DEFAULT', 'latitude', "0.0")
        self._config.set('DEFAULT', 'longitude', "0.0")

        self._config.add_section('gps')
        self.previous_position = (0.0, 0.0)

    def load(self):
        """Read the config file and place specific values in attributes."""
        self._config.read(self._filename)

        self.previous_position = (
            float(self._config.get('gps', 'latitude')),
            float(self._config.get('gps', 'longitude'))
        )

    def save(self):
        """Save the config file from specific values in attributes."""
        self._config.set('gps', 'latitude', str(self.previous_position[0]))
        self._config.set('gps', 'longitude', str(self.previous_position[1]))

        with open(self._filename, 'w') as configfile:
            self._config.write(configfile)

def gps_str2float(value):
    """Convert a coordinate (either latitude or longitude) in the Exiv2 format
    to a floating point value suited for OsmGpsMap.

    The coordinate is a string looking like "49/1 50/1 23546/6000"
    """
    assert isinstance(value, str)

    dms = search(r'^(\d+)/(\d+) (\d+)/(\d+) (\d+)/(\d+)$', value)

    try:
        (vdg, ddg, vmi, dmi, vse, dse) = dms.group(1, 2, 3, 4, 5, 6)
        degree = float(vdg) / float(ddg)
        minute = float(vmi) / float(dmi)
        second = float(vse) / float(dse)

        return degree + (minute / 60) + (second / 3600)
    except (AttributeError, ZeroDivisionError):
        return 0.0

def gps_float2str(value):
    """Convert a coordinate (either latitude or longitude) from OsmGpsMap
    floating point format to the Exiv2 format.

    The coordinate is a float.
    """
    assert isinstance(value, float)

    degree = int(value)
    minute = int(value * 60) % 60
    second = int(abs(value) * 3600 * 6000) % (60 * 6000)

    return "%d/1 %d/1 %d/6000" % (degree, minute, second)

class PropertyPage(object):
    """The interface is made of an OsmGpsMap and some buttons"""
    def __init__(self):
        self.page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.page.props.margin = 5

        # Add the map
        self.themap = OsmGpsMap.Map()
        self.themap.set_zoom(15)
        self.themap.layer_add(
            OsmGpsMap.MapOsd(
                show_zoom=True,
                show_crosshair=True
            )
        )

        self.page.pack_start(self.themap, True, True, 5)

        # Add error message
        self.error = Gtk.Label('This file does not contain GPS coordinates.')
        self.page.pack_start(self.error, True, True, 5)

        # Add the buttons
        self.buttons = Gtk.ButtonBox()

        self.btn_origin = Gtk.Button('Move to original position')
        self.btn_last = Gtk.Button('Move to last position')
        self.btn_apply = Gtk.Button('Apply')

        self.buttons.pack_end(self.btn_origin, False, False, 0)
        self.buttons.pack_end(self.btn_last, False, False, 0)
        self.buttons.pack_end(self.btn_apply, False, False, 0)

        self.page.pack_end(self.buttons, False, False, 0)

        # Show all widgets except the error message
        self.page.show_all()
        self.error.hide()

        # Property label
        self.property_label = Gtk.Label('GPS coordinates')
        self.property_label.show()

        # Convert XPM icon to Pixbuf
        self.icon = GdkPixbuf.Pixbuf.new_from_xpm_data(get_xpm_icon())

# pylint: disable=R0904
class ExifGpsProperty(GObject.GObject, Nautilus.PropertyPageProvider):
    """Operate a GUI displaying an OpenStreetMap map and an image preview, and
    let the user modify the GPS coordinates.
    """
    def __init__(self):
        self.config = Configuration('exifgpsproperty.ini')
        self.config.load()

        self.meta = None
        self.original_position = (0, 0)
        self.elements = None

    def move_to(self, position):
        """Change the center of the map to a position (a tuple of 2 float). If
        None is passed, it centers on the coordinates of the map (useful
        because OsmGpsMap does not center correctly when resizing the window).
        """
        if position is None:
            lat = self.elements.themap.props.latitude
            lon = self.elements.themap.props.longitude
        else:
            (lat, lon) = position

        self.elements.themap.set_center(lat, lon)

    def load_image(self, filename):
        """Load an image while retrieving its GPS coordinates."""
        self.meta = GExiv2.Metadata(filename)

        try:
            self.original_position = (
                gps_str2float(self.meta['Exif.GPSInfo.GPSLatitude']),
                gps_str2float(self.meta['Exif.GPSInfo.GPSLongitude'])
            )

            (lat, lon) = self.original_position
            self.elements.themap.image_add_with_alignment(
                lat,
                lon,
                self.elements.icon,
                0.5,
                1.0
            )
            self.move_to(self.original_position)

            # Disable "Apply" button if Exiv2 is not able to write metadata
            if not self.meta.get_supports_exif():
                self.elements['btn_apply'].props.sensitive = False
        except KeyError:
            # GPS coordinates could not be found, show the error message
            self.original_position = (0.0, 0.0)
            self.elements.themap.hide()
            self.elements.buttons.hide()
            self.elements.error.show()

    def load_images(self, filenames):
        """Load images while retrieving their GPS coordinates."""
        (minlat, maxlat, minlon, maxlon) = (500.0, -500.0, 500.0, -500.0)
        found = False

        for filename in filenames:
            meta = GExiv2.Metadata(filename)

            try:
                (lat, lon) = (
                    gps_str2float(meta['Exif.GPSInfo.GPSLatitude']),
                    gps_str2float(meta['Exif.GPSInfo.GPSLongitude'])
                )

                self.elements.themap.image_add_with_alignment(
                    lat,
                    lon,
                    self.elements.icon,
                    0.5,
                    1.0
                )

                found = True
                (minlat, maxlat) = (min(minlat, lat), max(maxlat, lat))
                (minlon, maxlon) = (min(minlon, lon), max(maxlon, lon))
            except KeyError:
                continue

        if not found:
            self.elements.themap.hide()
            self.elements.error.show()
        else:
            self.elements.themap.set_center(
                (minlat + maxlat) / 2,
                (minlon + maxlon) / 2
            )

    def save_image(self):
        """Save an image with the current GPS coordinates given by the user."""
        lat = self.elements.themap.props.latitude
        lon = self.elements.themap.props.longitude

        self.meta['Exif.GPSInfo.GPSLatitude'] = gps_float2str(lat)
        self.meta['Exif.GPSInfo.GPSLongitude'] = gps_float2str(lon)

        self.meta.save_file()

        self.config.previous_position = (lat, lon)

        self.config.save()

    def get_property_pages(self, files):
        """ Callback for Python-Nautilus defining property pages for Nautilus
        """
        # Clean file URIs
        filenames = []
        for one_file in files:
            if one_file.get_uri_scheme() != 'file':
                continue

            if one_file.is_directory():
                continue

            filenames.append(unquote(one_file.get_uri()[7:]))

        if len(filenames) == 0:
            return

        # Build property page
        self.elements = PropertyPage()

        if len(filenames) > 1:
            self.elements.buttons.hide()
            self.load_images(filenames)
        else:
            # Connects methods to elements
            self.elements.btn_origin.connect(
                "clicked",
                lambda _: self.move_to(self.original_position)
            )

            self.elements.btn_last.connect(
                "clicked",
                lambda _: self.move_to(self.config.previous_position)
            )

            self.elements.btn_apply.connect(
                "clicked",
                lambda _: self.save_image()
            )

            self.load_image(filenames[0])

        self.elements.themap.connect(
            "draw",
            (lambda _a, _b: self.move_to(None))
        )

        return [Nautilus.PropertyPage(
            name="ExifGPSProperty::GPSCoordinates",
            label=self.elements.property_label,
            page=self.elements.page
        )]

def get_xpm_icon():
    """Return an XPM icon used to show GPS point."""
    return [
        "44 55 17 1",
        " 	c None",
        ".	c #1600FF",
        "+	c #0814FF",
        "@	c #3232FF",
        "#	c #3F42FF",
        "$	c #534FFF",
        "%	c #5A5CFF",
        "&	c #6E70FF",
        "*	c #8483FF",
        "=	c #9090FF",
        "-	c #A1A1FF",
        ";	c #B0B0FF",
        ">	c #C5C5FF",
        ",	c #DBDBFF",
        "'	c #EBECFF",
        ")	c #FAFAFF",
        "!	c #FEFFFC",
        "    ....................................    ",
        "  ........................................  ",
        " .......................................... ",
        " ...............%-#........................ ",
        "...............*!')#........................",
        "..............*!-+,,+.......................",
        ".............*!-..#);.......................",
        "............+);....&!*......................",
        "............+)>@....-)$.....................",
        ".............%''$...+,'@....................",
        "..............@>)=+..@'>+...................",
        "..........+....+-!>+..%)=...................",
        ".........*!>.....%''$..;,..++...............",
        "........$)!)+.....@>)=%);.%))=..............",
        ".......@)!!=.......+-)!>+%);=!&.............",
        ".......;!!>.+-;+.....#%+$);..,;.............",
        "......#!!'+.*!!&.......$);..=!%.............",
        "......;!!*.@)!!#......#);..=!*..............",
        ".....+)!)+.,!!-.+#+...;,+.*!*.$#............",
        ".....$!!;.$!!,+.;!>...=)#=!*+>!!-+..........",
        ".....*!!&.*!!&.%!!,...+>!!*.=)**)>@.........",
        ".....-!!#.;!!#.>!!&....+$@..>>..%''$........",
        ".....>!!@.,!!+.)!)..........*!&..@,)*.......",
        ".....>!!+.,!)+.)!)...........>'@..+;!;+.....",
        ".....;!!@.;!!#.>!!%...+$+....@'>+...*),@....",
        ".....=!!%.*!!&.&!!)*#&'!;.....%)=....$',....",
        ".....%!!-.$!!,+.>!!!!!!!>......=)%....-)+...",
        ".....+!!'.+,!!*.+;!!!!!>+......+>'@..=!=....",
        "......>!!%.#!!)$..#*;=$..@>;+...@'>.=!-.....",
        "......%!!,..-!!!-+.....+*)!!$....&!>!-......",
        ".......,!!*.+>!!!'-&$&-,!!!,+.....*,*.......",
        ".......$!!!%.+*)!!!!!!!!!!-+.@#+............",
        "........=!!)%..@>!!!!!!!,$..&)!&............",
        ".........;!!!=+..+$*-*$+..+-!!!*............",
        ".........+;!!!'&+.......+*'!!!;+............",
        "...........*!!!!)>*&%&=>)!!!)*..............",
        "............#>!!!!!!!!!!!!!>@...............",
        "..............#-'!!!!!!!'-#.................",
        ".................@%&*&%@....................",
        "............................................",
        "............................................",
        " .......................................... ",
        "  ........................................  ",
        "   ......................................   ",
        "                ............                ",
        "                 ..........                 ",
        "                 ..........                 ",
        "                  ........                  ",
        "                  ........                  ",
        "                   ......                   ",
        "                   ......                   ",
        "                    ....                    ",
        "                     ..                     ",
        "                     ..                     ",
        "                                            ",
    ]
