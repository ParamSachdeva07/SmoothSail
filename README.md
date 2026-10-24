# SmoothSail

A responsive, interactive Mapbox GL JS globe that renders Natural Earth land as crisp white dots on pure black. It has no ocean sphere, texture, labels, borders, or atmosphere.

The Mapbox logo and attribution are retained as required provider attribution.
The previous flat-map image and raster mask are no longer used; all globe geography comes from the Natural Earth land polygons.

## Run locally

1. Install dependencies with `npm install`.
2. Copy `.env.example` to `.env.local` and set `VITE_MAPBOX_ACCESS_TOKEN` to a Mapbox public token. Restrict the token to allowed origins such as `localhost`; do not commit `.env.local`.
3. Start the Vite server with `npm run dev` and open the local URL it prints.

The map reports a helpful message if the token is missing or rejected. A Mapbox public token is required for Mapbox GL JS and is visible in the browser, so restrict it by URL and scope.

## Geographic data

Generate the five precomputed density levels with `npm run data:generate`. The script downloads Natural Earth 1:10m land GeoJSON into `assets/natural-earth-land.geojson` if it is not present, rasterizes its polygon rings once into a cached 0.05° binary mask, then writes compact GeoJSON point datasets under `public/data/`. It samples polygon land only; country boundaries are not included. Data is public domain; see `assets/natural-earth-attribution.txt`.

## Interaction and visual settings

- Drag or touch-drag to rotate; wheel/trackpad to zoom toward the pointer; pinch to zoom.
- Zoom is constrained between the configured minimum and maximum and anchored at the globe center so edge zooms cannot move the globe out of view. The finest dots remain visible at the upper limit. Drag release has inertia; automatic rotation is off by default.
- Edit `SETTINGS` in `src/settings.js` to change color, dot radii, geographic interval per density level, fade ranges, zoom limits, initial view, interaction sensitivity, inertia, and optional rotation. The globe renderer and dataset generator both read this same file.

The zoom sequence is tuned to the visual reference: it starts with a close-spaced global grid, keeps dots close to the same small on-screen size, and progresses from 1° spacing down to 0.1875° so coastlines and islands fill in as you zoom. Adjacent density layers overlap and crossfade; each level's radius adjusts only slightly through the transition. After changing `spacing`, run `npm run data:generate` again to rebuild the datasets.

Dots remain crisp, map-aligned circular marks while the globe projection foreshortens their distribution toward the limb and hides the rear hemisphere.
