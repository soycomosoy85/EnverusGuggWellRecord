# Build Enverus Gugg Well Record

Current national Enverus acquisition, incremental synchronization, and Gugg well enrichment. The workflow produces **file-geodatabase feature classes only**. Shapefile generation is not supported by manual runs, nightly updates, or runtime transfers.

This repository contains current code, configuration schemas, blank ArcGIS/Excel templates, API field definitions, and automated tests. Keep credentials, Gugg reference inputs, downloaded records, processing caches, and GIS outputs private.

## Outputs

`Gdb/NorthAmerica/Output/EnverusGuggWellRecord.gdb` contains exactly four feature classes:

| Feature class | Purpose |
| --- | --- |
| `EnvLateral_Gugg` | Selected producing lateral geometry, one record per country and full base API/UWI origin. Survey laterals take precedence over Enverus lateral fallback geometry. |
| `EnvWell_Gugg` | Original Enverus lateral geometries for mapping, retaining eligible source API14 records and the selected well attributes. |
| `EnvWellCentroid_Gugg` | Point halfway along the analytical line in its local projection. Verticals and point-only wells use the surface location. |
| `EnvSH_Gugg` | Surface-hole points from the selected records' cached `ShlLon` and `ShlLat`, with the complete well attributes. |

`Gdb/NorthAmerica/Output/EnverusContext.gdb` contains pipelines, facilities, operator land, active rigs, and mapped M&A transactions. Records without usable geometry remain in the source cache and are counted. PWI DSUs remain disabled pending API entitlement.

The approved field dictionary defines **102 fields**, including `GuggGisBsn`, `WellConstr`, and `WelCnsStat`. It controls field order, short field names, descriptive aliases, and types. Identifiers are text; dates are normalized; NULLs and complete text values are preserved. Text fields expand when necessary. `EnvDsuId` remains NULL until its source is supplied. `RecKey` is the stable internal feature key and is hidden in the ArcGIS project.

## Install

1. Install and sign in to licensed ArcGIS Pro compatible with the supplied Pro 3.6 project template.
2. Clone/download this repository.
3. Privately extract `GuggReferenceInputs.zip` into the repository root. Required inputs include `Gdb/Reference/GuggenheimReference.gdb` and `Json/Config/WellConstraintStatus.Local.json`. Do not upload this private asset to GitHub.
4. Configure credentials on each computer using the Windows account that will run the workflow:

```powershell
.\Ps1\SetEnverusCredentials.ps1 -ApiVersion 3
.\Ps1\RunWellRecord.ps1 -Action validate
```

Credentials use Windows account/computer encryption and must be configured again on another machine. Tokens stay in memory. ArcPy is supplied by Pro; other requirements are in `requirements.txt`. Launchers accept `-ProPython` for another Pro installation.

## Run

```powershell
.\Ps1\RunNationalRebuild.ps1               # Build wells from cache and update all enabled context datasets
.\Ps1\RunNationalRebuild.ps1 -SyncSources  # Also perform an immediate well-source sync
.\Ps1\RunWellRecord.ps1 -Action sync      # Well-source synchronization only
.\Ps1\RunWellRecord.ps1 -Action build     # Well products from the existing cache
.\Ps1\RunWellRecord.ps1 -Action test      # Licensed local tests
```

The scope is all account-entitled North America records, with no basin or country filter. Cancelled/expired permits and their known vendor spelling variants are excluded; permitted and pending-approval wells remain. Full Canadian UWIs are preserved.

The first source baseline is checkpointed. Later syncs read identifier/timestamp inventories and download changed well payloads and affected directional surveys. Survey updates/deletions use a three-day overlap. Watermarks advance only after successful synchronization. Unexpected membership removals stop publication for review. OS locks prevent overlapping updates.

Later GIS runs evaluate affected origins and write only changed features. Unchanged feature ObjectIDs are retained. Timestamp-only changes with identical outputs cause no GIS writes. Reference or geometry-rule changes can require broader local processing. Cached survey calculations, selected records, and source lineage stay in SQLite.

`Ps1/ResumeGeodatabaseOnly.ps1` finishes a verified completed-core GDB checkpoint and populates the surface-hole layer from cached coordinates. It does not rerun the survey geometry engine or Gugg spatial assignments. This is a recovery entry point; normal operation uses the national or nightly launcher.

## Geometry and Gugg rules

Actual directional surveys take precedence. Producing laterals use interpolated perforation bounds, otherwise the longest sampled interval with inclination at least 80 degrees. Planned surveys are permitted in New Mexico. Fallbacks trim backward from a verified toe by reported lateral length. Uncertain geometry is retained and flagged for allocation review.

Measurements use a local UTM/UPS projection per well; final features use WGS84 XY. Survey Z and its units/provenance remain internal. Use the same measurement basis for tract intersections and allocation denominators.

Nomenclature matches region, basin, and interval. A TCA must match both Gugg Basin and Gugg Bench; greatest positive lateral overlap determines the primary TCA, identified by unique `TCA_NAME`. Fluid windows and GIS basins use greatest lateral overlap. Verticals and point-only wells use surface containment for the GIS basin. Ambiguities and unmatched inputs are reported.

`Spacing_Ft = 5280 / WPS`; `DA_Ft = Spacing_Ft / 2`. Invalid WPS produces NULL and a review flag.

`WellConstr` is TEXT(1), defaults to N, and is Y only for Horizontal or Directional wells with usable lateral geometry intersecting a basin/bench-matched TCA. All other trajectories and surface-only records remain N. This flag is independent of the primary TCA winner, so tied TCAs can still qualify.

`WelCnsStat` is TEXT(6), alias **Well Constraint Status**, immediately after `WellConstr`. It looks up `EnvStatus` using the private status mapping, independently of the Y/N flag. Missing or unlisted statuses remain NULL and are reported. All well products inherit these attributes.

## Nightly operation and validation

`Ps1/InstallNightlyTask.ps1` installs a daily **1:00 AM local-time** Windows task that syncs sources and updates changed GIS features. It preserves the configured source cache, catches up missed starts, and skips overlapping work. The default requires the configured Windows account to remain logged on, with the PC awake/online and Pro licensing available. Installing code alone does not install a task.

Final readiness is recorded in `Json/Config/LatestNationalRebuild.json`. Validation checks all four actual well feature classes, registry/report counts, field order and aliases, constraint attributes, and all enabled context datasets. A GDB directory or intermediate report is not proof of completion. Runtime state and diagnostics are under `Log/NorthAmerica` and `Json/NorthAmerica`.

AGOL publication remains disabled pending QC. The current AGOL utilities provide readiness and local subset preparation only; they do not publish.

## Private transfer and folders

`Py/CacheTransfer.py export --include-gis` packages the well source cache, processing state, and managed well GDB. Import with `--manifest <path>` on the destination. Transfers contain licensed data and must remain private. Context caches/outputs are initialized separately on the destination. Credentials and source code are not included in data transfers.

CamelCase format folders include `Py`, `Ps1`, `Json`, `Aprx`, `Atbx`, `Gdb`, `Sqlite`, `Xlsx`, `Pdf`, `Xml`, and `Zip`. Runtime directories and private local configuration are ignored by Git. Retired pilot, TX/NM QC, and obsolete migration utilities are not part of the current distribution.
