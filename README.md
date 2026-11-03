# Build Enverus Gugg Well Record

Maintain an incremental Enverus source cache and enrich analytical/display well geometries with Gugg nomenclature, type curve areas, and fluid windows. NorthAmerica has no basin or country filter. Cancelled and expired permits are excluded; null-status wells are retained and flagged.

## Final products

`Gdb/<Profile>/Output/EnverusGuggWellRecord.gdb` contains exactly four feature classes:

| Feature class | Geometry and use |
| --- | --- |
| EnvLateral_Gugg | One selected analytical lateral per country/full base API_UWI origin. Actual survey lateral takes precedence, followed by allowed planned surveys and trimmed Enverus lateral fallback. |
| EnvWell_Gugg | Original Enverus lateral geometry retaining eligible source API14s, with selected well attributes. Use for map display. |
| EnvWellCentroid_Gugg | Half-distance point along each selected analytical line, measured in the well's local projection. Vertical wells and point-only wells use the surface hole. |
| EnvSH_Gugg | Surface-hole points from the selected well's existing `ShlLon`/`ShlLat` attributes, carrying the complete template and Gugg columns. No API, survey, or polygon recalculation is performed for this final step. |

Midpoints lie on the line rather than at the bounding-box or polygon centroid. Origins without coordinates remain in the processing cache but cannot produce a point. Surface-hole points use one selected record per well origin; missing or invalid surface coordinates are omitted and counted in the surface-hole report. The final GDB contains no supporting tables or additional layers; surveys, alternative completions, and source identities remain internal in SQLite.

The supplied well template defines field names, aliases, and order in `Json/Config/FieldDictionary.json`: 99 unique columns after retaining `EnvWellId` once. `EnvDsuId` is text and NULL until a source is specified. Country-safe grouping preserves complete Canadian UWIs; the template alias “API 10” does not truncate them.

## Install

Clone/download source and privately extract `GuggReferenceInputs.zip` into the root. The asset supplies `Gdb/Reference/GuggenheimReference.gdb` with only nomenclature, TCAs, fluid windows, and vendor documentation. Keep it and all runtime transfers out of a public repository or release. Source files contain no well data or credentials.

Install/sign in to licensed ArcGIS Pro compatible with the Pro 3.6 project template. ArcPy comes from Pro; `requests` is normally installed. In PowerShell at the root:

```powershell
.\Ps1\SetEnverusCredentials.ps1 -ApiVersion 3
.\Ps1\RunWellRecord.ps1 -Action validate
.\Ps1\RunWellRecord.ps1 -Action test
```

Credentials are encrypted for each Windows account/computer and must be configured separately on the work PC. Tokens remain in memory. Launchers accept `-ProPython` for another Pro install path.

## Run and migrate

```powershell
.\Ps1\RunWellRecord.ps1 -Action run    # Sync and build
.\Ps1\RunWellRecord.ps1 -Action sync   # Source updates only
.\Ps1\RunWellRecord.ps1 -Action build  # Build from cache, no API download
```

The first baseline checkpoints pages and completed survey batches. Incremental sync reads a thin identifier/timestamp inventory, retrieves changed well payloads, and independently checks survey update/deletion timestamps with a three-day overlap. Full surveys are fetched only for eligible affected wellbores. A successful refresh alone advances the watermark. Unexpected removals over 5% stop publication for review. OS locks prevent concurrent runs.

Template expansion triggers a resumable backfill of new header fields plus identifying metadata, without redownloading surveys. Run sync before building the expanded schema.

For an existing installation changing to these names/columns:

```powershell
.\Ps1\RunWellRecord.ps1 -Action sync
.\Ps1\RunWellRecord.ps1 -Action migrate
.\Ps1\RunWellRecord.ps1 -Action build
```

`migrate` verifies new header coverage and archives old GIS registry tables in the processing database. Source surveys and previous output files remain. The first revised-schema build initializes the revised core products once. The surface-hole layer is an additive final cached-data step and can be populated on an existing build without recomputing survey or Gugg assignments. Later updates evaluate affected origins and write only changed features; unchanged ObjectIDs remain. A timestamp-only change with identical outputs causes no GIS writes. References/geometry-rule changes may require broader local evaluation. Use newly exported runtime transfers with this source version; previous-schema archives need the corresponding previous version.

## Geometry and enrichment

Actual survey laterals use interpolated perforation MD bounds, otherwise the longest contiguous sampled run with inclination at least 80 degrees. Planned surveys are allowed in New Mexico by default and labelled. Fallbacks use toe-back clipping by reported lateral length when the toe is verified. Missing lengths, uncertain toes, multipart paths, and target lengths exceeding the mapped path remain flagged for allocation review.

Per-well UTM/UPS projections supply lengths and half-distance points; outputs use WGS84 XY. Use the same measurement basis for tract intersections and allocation denominators. Survey Z remains internal with original units/provenance.

Nomenclature matches `(ENVRegion, ENVBasin, ENVInterval)`. TCAs must match Gugg Basin/Bench; longest positive lateral overlap wins and `TCA_NAME` is unique. Fluid windows also use longest overlap. `Spacing_Ft = 5280 / WPS`; `DA_Ft = Spacing_Ft / 2`. Invalid WPS yields NULL. Outside Gugg coverage, wells remain with unmatched flags.

Fields are at most ten characters with descriptive aliases. Dates are date-only; source month-only dates use day one with a precision flag. Identifier fields are text. Shapefile numeric NULLs use `-999999999`, text NULLs use blanks, and `NullCount` reports missing business values. The GDB preserves exact NULLs/full text. Overlong shapefile text uses `SeeGdb:<WellKey>`. `RecKey` is the stable feature key, final template column, and hidden in supplied layers. Never persist shapefile FIDs as identifiers. Parts respect configured text widths and byte/record limits; only affected parts/rows are updated. Disable exports with `exportShapefiles: false`; pending changes remain queued.

## Private transfer

`Ps1/RunBaseline.ps1` syncs, builds, then exports complete GIS/cache state per `Workflow.json`. Manual export/import:

```powershell
& 'C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat' .\Py\CacheTransfer.py export --include-gis --build-gis-first
& 'C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat' .\Py\CacheTransfer.py import --manifest 'D:\Transfer\CacheTransferManifest.json'
```

Keep the manifest and every numbered 1 GiB part together in private storage. They contain licensed source/cache/GIS state, exclude credentials/code/reference inputs, and are verified by hashes, scope, watermark, and SQLite integrity. Complete state supports changed-well updates on the work PC; relocated project paths refresh without rewriting wells. Source-only transfers require one initial local GIS build.

## Nightly updates and folders

Windows Task Scheduler defaults to **1:00 AM work-PC local time**, syncing and updating changed GIS records:

```powershell
.\Ps1\InstallNightlyTask.ps1 -Preview
.\Ps1\InstallNightlyTask.ps1
# Optional logged-out execution; Windows stores the account password:
.\Ps1\InstallNightlyTask.ps1 -RunWhenLoggedOff
```

The default task runs while logged on, including a locked screen. Power/network and usable Pro licensing are required. Missed starts catch up, failures retry, and overlapping runs are skipped. Scheduled jobs wait for source/GIS initialization rather than silently starting a national build. Downloading code installs no task. Remove using `InstallNightlyTask.ps1 -Remove`.

CamelCase format folders: `Py`, `Ps1`, `Json`, `Aprx`, `Atbx`, `Gdb`, `Shp`, `Lyrx`, `Sqlite`, `Pdf`, `Zip`. Git ignores runtime data and secrets. A disk reserve stops work without deleting previous deliveries. Synthetic tests cover updates/deletions, field backfill, midpoint placement, final schema, stable IDs, no-op runs, and relocation. ArcPy tests run locally; CI uses synthetic tests without API credentials.
