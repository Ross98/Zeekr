# Third-party attribution

## Vehicle images

The overview uses an unmodified Zeekr 001 product image from Zeekr's official
European model page, retrieved 2026-09-17. It is embedded locally in
`zeekr_control/static/car.svg`; the SVG viewport trims transparent margins only.
The vehicle details page uses the same original PNG bytes extracted into
`zeekr_control/static/car-001.png`, without a vector wrapper or image edits.
Vehicle color, regional specification and trim are illustrative and do not
identify any owner's exact vehicle configuration. Rights remain with the
original rights holder; no open-source image license is claimed.

Source page: https://www.zeekr.eu/models/001
Original asset: https://www.datocms-assets.com/128969/1741166816-001.png?w=1200&fm=png

## Web map

The Web interface includes Leaflet 1.9.4 (BSD-2-Clause), copyright Vladimir
Agafonkin and CloudMade. The full license is retained in
`zeekr_control/static/vendor/LEAFLET-LICENSE.txt`.
Source: https://github.com/Leaflet/Leaflet/tree/v1.9.4

Map data is provided by OpenStreetMap contributors, subject to the ODbL.
Tiles are loaded directly from https://tile.openstreetmap.org only after the
user enables location display. Map attribution is visible in the map.
Copyright: https://www.openstreetmap.org/copyright
Tile policy: https://operations.osmfoundation.org/policies/tiles/

## Gateway protocol

GW1/GW2 and read-only GW3 history signing adapted from RexzeLu/zeekr_ha, commit 316ce6e7ea718b3d5ba4597bf87627904add5330.
Source: https://github.com/RexzeLu/zeekr_ha/blob/316ce6e7ea718b3d5ba4597bf87627904add5330/custom_components/zeekr_ev/api_sms.py

History request methods and parameter contracts also reference Fryyyyy/zeekr_ev_api,
commit 4dc9e1789e577864003f9e27b293ade8d47e1e70 (MIT, same copyright below).
Source: https://github.com/Fryyyyy/zeekr_ev_api/blob/4dc9e1789e577864003f9e27b293ade8d47e1e70/src/zeekr_ev_api/client.py
Domestic compatibility is not established by the overseas implementation.

MIT License

Copyright (c) 2025 Fryyyyy

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
