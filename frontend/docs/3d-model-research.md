# 3D model source research

Goal: find a free ant model suitable for a browser-rendered swarm of hundreds to thousands of agents.

## Ranked sources

1. Poly Pizza
   - URL: https://poly.pizza/
   - Good fit for this project because it exposes lightweight GLB/OBJ-style assets and the selected ant file is small enough for instancing.
   - Chosen asset: https://poly.pizza/m/90PJjBye5ZC
   - Verified June 13, 2026: the asset page lists OBJ/GLTF format and Creative Commons Attribution.
   - Tradeoff: low-poly/stylized; not rigged. We compensate with procedural gait/leg animation in the renderer.

2. Sketchfab
   - URL: https://sketchfab.com/
   - Best catalog for realistic insect scans and artist models; Sketchfab supports downloadable Creative Commons models, but each asset needs a license and format review.
   - Tradeoff: many high-quality ant models are large, not consistently GLB-direct, require download/API flow, or are not cleanly animation-ready for instancing.

3. Quaternius
   - URL: https://quaternius.com/
   - Excellent free game assets, nature packs, and animated animal packs.
   - Tradeoff: no better realistic ant source found for this use case; useful for future environment/creature packs.

4. Kenney
   - URL: https://kenney.nl/assets
   - Excellent CC0 game assets with clean packaging.
   - Tradeoff: more stylized/general game packs, not a realistic ant replacement.

5. OpenGameArt
   - URL: https://opengameart.org/
   - Broad free-asset catalog with many license types.
   - Tradeoff: quality and licensing are inconsistent; needs per-asset review.

## Current decision

Keep the Poly by Google ant GLB as the body source, with attribution in `public/models/ANT_MODEL_ATTRIBUTION.md`. Use renderer-side animation and simulation constraints to make the colony feel real: animated legs, water avoidance, terrain-following pitch/roll, pheromone paths on land, and grounded contact.
