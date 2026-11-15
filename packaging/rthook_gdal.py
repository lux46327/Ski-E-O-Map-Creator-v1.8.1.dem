"""PyInstaller runtime hook: point GDAL and PROJ at the data folders bundled with rasterio (the exe has no installed GDAL).
Without them every GeoTIFF with an EPSG code (swissALTI3D, TINITALY ...) fails with "Cannot find proj.db"."""
import os
import sys

_base = getattr(sys, '_MEIPASS', None)
if _base:
    for _name, _vars in (('gdal_data', ('GDAL_DATA',)), ('proj_data', ('PROJ_DATA', 'PROJ_LIB'))):
        for _root in (os.path.join(_base, 'rasterio', _name), os.path.join(_base, _name)):
            if os.path.isdir(_root):
                for _v in _vars:
                    os.environ[_v] = _root
                break
