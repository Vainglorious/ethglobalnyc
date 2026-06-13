# Tree1 asset notes

- Source archive: `/Users/hemangvora/Downloads/1f9jtr180dxk-Tree1ByTyroSmith.zip`
- Imported trial file: `Tree1.3ds`
- Trial textures: `Leaves0120_35_S.png`, `BarkDecidious0143_5_S.jpg`
- Original archive also contains a very large OBJ/MTL/Blend version.

## Analysis

- `Tree1.3ds` parses with Three.js `TDSLoader`.
- Parsed geometry: 1 mesh, 145 vertices, 224 triangles.
- Approximate source-space bounds: 40.3 x 87.9 x 32.9.
- This is appropriate for a small authored scene patch.
- The OBJ is about 49 MB and 1.6 million lines, so it should not be shipped as-is.

## Current use

`src/components/world/AssetTreePatch.tsx` uses the `.3ds` version for three specimen trees beside the first-load trail. The asset reads closer to a foliage card than a full separated tree, so it is useful as a visual test patch but should be converted/cleaned before replacing the wider procedural forest.

## Grass archive

`/Users/hemangvora/Downloads/51-grass.rar` extracts to `Grass.c4d`. That file is a Cinema 4D scene and is not directly loadable by the current Three.js pipeline. It needs conversion to GLB/OBJ/FBX before it can be integrated.
