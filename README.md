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

The supplied well template defines field names, aliases, and order in `Json/Config/FieldDictionary.json`: 99 unique template columns after retaining `EnvWellId` once, plus the requested derived `GuggGisBsn` and `WellConstr` columns, for 101 total. `EnvDsuId` is text and NULL until a source is specified. Country-safe grouping preserves complete Canadian UWIs; the template alias “API 10” does not truncate them.

## Install

Clone/download source and privately extract `GuggReferenceInputs.zip` into the root. The asset supplies `Gdb/Reference/GuggenheimReference.gdb` with nomenclature, TCAs, fluid windows, GIS basin polygons, and vendor documentation. Keep it and all runtime transfers out of a public repository or release. Source files contain no well data or credentials.

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

`GUGG_GIS_Basin.GuggGisBsn` supplies the broader GIS basin assignment, independently of TCA/bench matching. Lines use longest positive lateral overlap, while verticals and point-only wells use their surface locations. Multiple overlaps and ties are flagged; ties remain NULL. Geometries remain intact. The assignment is inherited by the display, centroid, and surface-hole products.

`WellConstr` (alias “Well Constraint”) is TEXT(1), defaults to `N`, and is inherited by all four well products. It becomes `Y` only for Horizontal or Directional trajectories with usable lateral geometry intersecting at least one TCA with both a matching nomenclature Gugg Basin and Gugg Bench. All other trajectories, surface-only records, and unmatched wells remain `N`. The flag is independent of the primary TCA winner: even a TCA tie can constrain future inventory. A boundary-only intersection is an intersection and is flagged for review.

`WelCnsStat` (alias “Well Constraint Status”) is TEXT(6), immediately after `WellConstr`, and looks up `EnvStatus` for every well regardless of its Y/N flag. Install `Json/Config/WellConstraintStatus.Local.json` from the private reference package. Unlisted or missing statuses remain null and appear in the attribute QC report. This lookup and the trajectory restriction are attribute rules: changes do not require survey processing or spatial joins. Existing outputs can be updated with `Py/UpgradeWellAttributes.py --root <runtimeRoot>` under the workflow lock. The one-time ordered feature copy preserves geometry and stable record keys, verifies counts and geometry checksums, and refreshes tracked ObjectIDs. Later lookup edits update attributes in place. The compiled `FieldDictionary.json` governs the added column; the original user header workbook is retained unchanged.

Fields are at most ten characters with descriptive aliases. Dates are date-only; source month-only dates use day one with a precision flag. Identifier fields are text. Shapefile numeric NULLs use `-999999999`, text NULLs use blanks, and `NullCount` reports missing business values. The GDB preserves exact NULLs/full text. Overlong shapefile text uses `SeeGdb:<WellKey>`. `RecKey` is the stable feature key, final template column, and hidden in supplied layers. Never persist shapefile FIDs as identifiers. Parts respect configured text widths and byte/record limits; only affected parts/rows are updated. Disable exports with `exportShapefiles: false`; pending changes remain queued.

## Private transfer

`Ps1/RunBaseline.ps1` syncs, builds, then exports complete GIS/cache state per `Workflow.json`. Manual export/import:

```powershell
& 'C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat' .\Py\CacheTransfer.py export --include-gis --build-gis-first
& 'C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat' .\Py\CacheTransfer.py import --manifest 'D:\Transfer\CacheTransferManifest.json'
```

Keep the manifest and every numbered 1 GiB part together in private storage. They contain licensed source/cache/GIS state, exclude credentials/code/reference inputs, and are verified by hashes, scope, watermark, and SQLite integrity. Complete state supports changed-well updates on the work PC; relocated project paths refresh without rewriting wells. Source-only transfers require one initial local GIS build.

## Nightly updates and folders

### Context datasets

`Json/Config/ContextLayers.json` enables pipelines, facilities, operator land, active rigs, and M&A transaction polygons. PWI DSUs remain disabled pending API entitlement. Context layers have independent SQLite caches/watermarks and an independent process lock; failure in one layer preserves its previous cache and does not erase successful layers. They are stored in `Gdb/<Profile>/Output/EnverusContext.gdb`, separate from the four well products.

```powershell
& 'C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat' .\Py\ContextLayers.py run
```

Each refresh reads a thin identifier/timestamp inventory, requests only new/changed full records, and removes features that leave the source inventory. This includes rigs becoming inactive. Initial acquisition is complete once; saved pending payloads support retries. NULL update timestamps force a fresh payload check. Duplicate identifiers, inconsistent inventory/payload snapshots, and excessive removals stop publication of that cache. GIS feature hashes retain unchanged ObjectIDs and retry an acknowledged GIS batch idempotently after failures.

Context output retains source attributes with short field names and full source aliases; raw payloads remain in SQLite. Field dictionaries are stored under `Json/<Profile>/Context`. Context exports use a GDB rather than shapefiles: the M&A source has more than the shapefile column limit. Missing/invalid geometries are counted while source records remain cached.

Partial context dates use date-only values with explicit precision in `DateInfo`: a year uses January 1 and a year/month uses day 1, with the original source text retained alongside the precision. Unparseable dates remain NULL and their source text is retained for review. The source cache always preserves the unconverted value. Context reports distinguish total source records from records with a usable mapped feature.

The nightly launcher now runs the well workflow and context refreshes, followed by a local AGOL readiness check. It does not upload data. Context refreshes can proceed independently while an initial well build is still running.

### ArcGIS Online test publication

The supplied `GUGG_GIS_Basin` polygon feature class and `GuggGisBsn` name field are configured in `Json/Config/ArcGisOnline.json`. Publishing and automatic subset preparation are held until the user completes QC of the finished data (`awaitUserQualityControl: true`). After QC, `AgolPreflight.py --prepare-subset` checks readiness and prepares a local size/count report only; it never creates or updates hosted content. Paused/incomplete source builds are not eligible for subset preparation. Review the subset report before implementing/enabling hosted publication.

The publication boundary is these broader GIS basins, including fringe wells. Well products are filtered by their basin assignment; context features are selected spatially. Whole features are copied instead of clipping analytical lines. The local report includes per-layer counts, well counts by basin, staging size, and sample-based hosted-storage planning estimates. Estimates are not a storage-credit quote. The full national cache is not a publication input. The proposed remote publishing stage keeps initial items private, retains stable item/layer identifiers, and uses keyed add/update/delete operations; it remains a subsequent setup step and is not implemented by the local readiness/subset commands.

Authenticate on the publishing machine under the intended organization account. ArcGIS Pro sign-in can be used during testing; persistent unattended authentication must be verified under the Windows task account. Store organization identity/profile settings in ignored `*.Local.json` files, never passwords/tokens in source. The work PC can then connect to the same hosted items using that account.

ArcGIS Online hosted feature storage incurs credits based on actual hosted size; local cache/GDB size is not an exact estimate. See [Esri storage rates](https://doc.arcgis.com/en/arcgis-online/administer/credits.htm). At the documented rate, 500 MB of hosted features is approximately 120 credits/month before other usage. The first subset needs a measured report rather than a national upload.

### Eventual server destination

The intended database destination is PostgreSQL with PostGIS geometry support. Context acquisition is independent of ArcPy and keeps stable source IDs, raw attributes, timestamps, and dirty queues that can feed a future PostGIS upsert sink. That sink is not yet implemented. The existing well geometry engine still uses ArcPy; moving it to a server requires appropriate ArcGIS licensing/runtime or a separately validated port. Keep acquisition, enrichment, storage, and publication separate so AGOL remains a delivery layer and a future PostGIS database can become the system of record.

Windows Task Scheduler defaults to **1:00 AM in the executing PC's local time**, syncing and updating changed GIS records. It is currently installed on the test PC; manual download workers can be paused independently without disabling that task:

```powershell
.\Ps1\InstallNightlyTask.ps1 -Preview
.\Ps1\InstallNightlyTask.ps1
# Optional logged-out execution; Windows stores the account password:
.\Ps1\InstallNightlyTask.ps1 -RunWhenLoggedOff
```

The default task runs while logged on, including a locked screen. Power/network and usable Pro licensing are required. Missed starts catch up, failures retry, and overlapping runs are skipped. Scheduled jobs wait for source/GIS initialization rather than silently starting a national build. Downloading code installs no task. Remove using `InstallNightlyTask.ps1 -Remove`.

CamelCase format folders: `Py`, `Ps1`, `Json`, `Aprx`, `Atbx`, `Gdb`, `Shp`, `Lyrx`, `Sqlite`, `Pdf`, `Zip`. Git ignores runtime data and secrets. A disk reserve stops work without deleting previous deliveries. Synthetic tests cover updates/deletions, field backfill, midpoint placement, final schema, stable IDs, no-op runs, and relocation. ArcPy tests run locally; CI uses synthetic tests without API credentials.

### Custom Texas and New Mexico delivery

Run `Ps1/RunCachedSubset.ps1` to prepare an independent TX/NM snapshot from an existing national cache and build the four well products. This makes no API requests, installs no scheduled task, and leaves the national output and its completion reports unchanged. The default destination is `CustomRuns/TexasNewMexico`; use `-OutputRoot` to choose another folder. The run copies only selected wellbores and their surveys, reuses compatible cached well calculations, and writes its state and log under `Log/TexasNewMexico` within that destination. Re-running resumes the prepared snapshot; it does not refresh it from subsequent national syncs. Custom run folders contain licensed data and are excluded from Git.

GDB text fields expand when source values exceed the template width, preserving the full text. `WellConstr` remains one character. Shapefiles retain their declared DBF widths; oversized values use a bounded `SeeGdb` marker (or `?` for fields shorter than six characters), with the separate `WellKey` and `RecKey` fields identifying the full GDB record. The reviewed writer repair preserves compatibility with completed national geometry calculations through an exact code-hash mapping; other computation changes still invalidate the geometry cache.
