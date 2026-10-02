# Place map marker and navigation repair

User supplied a production screenshot with broken default marker images and overlapping permanent names; requested easier place lookup and jumps.

Scope: trip-tags.js, insights.css, ui_trip_places.cjs. Use bundled Leaflet divIcon numbered markers, transient name tooltips and selected-place popups. Place names in the table, directions and event endpoints open the map, focus it at zoom 17, scroll the map into view and expose a direct OpenStreetMap page link. Only explicit clicks reveal the map or open the external site. Unknown endpoints remain plain text. Show-all restores full extent. Retain viewport and focused place on UI paints; clear these on month/account/record invalidation and hiding the map. Keep name edits and 150 m clustering unchanged.

Regression first failed because the old map created two image markers. New coverage checks image-free markers, non-permanent labels, all three jump entry points, exact external URL and safe new-tab attributes, keyboard focus, repeat-jump map center, selected-place persistence, show-all and context reset. Existing layout/privacy/month tests retained. Synthetic desktop/mobile map inspection completed in two batches. Naming and all 40 refresh/scroll browser checks passed; syntax and diff checks passed. No backend logic or private data modifications; not deployed by this task.
