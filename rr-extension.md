# pyQuARC Extension: New Rules, Zenodo Format Support

This document records all changes made to pyQuARC to add new metadata quality rules and support for the Zenodo/InvenioRDM metadata format.

---

## 1. New Supported Format: `zenodo`

### `pyQuARC/code/constants.py`
- Added `ZENODO = "zenodo"`
- Added `ZENODO` to `SUPPORTED_FORMATS`

### `pyQuARC/code/checker.py`
- Imported `ZENODO` from constants
- Updated the `run()` method parser selection so Zenodo is treated as JSON (same as `umm-*`), not XML

### `pyQuARC/code/schema_validator.py`
- Imported `ZENODO` from constants
- Added a branch in `__init__` to skip structural schema validation for Zenodo (no XSD/JSON schema registered): `self.validator_func = lambda _: {}`

### `pyQuARC/main.py`
- Imported `ZENODO` from constants
- Added `zenodo` to the `--format` argument help text

---

## 2. New Check Functions

### `pyQuARC/code/string_validator.py` — class `StringValidator`

| Function | Description |
|---|---|
| `forbidden_values_check(value, forbidden_list)` | Checks the field value does not contain any string from `forbidden_list` (case-insensitive) |
| `min_length_check(value, min_length)` | Checks the field value is at least `min_length` characters long |
| `regex_check(value, pattern)` | Checks the field value matches a given regex pattern |

### `pyQuARC/code/custom_validator.py` — class `CustomValidator`

| Function | Description |
|---|---|
| `fields_not_equal_check(field_a, field_b)` | Checks two fields do not have the same value (case-insensitive) |
| `required_if_check(field_value, condition_value, expected_value)` | Checks `field_value` is present when `condition_value` equals `expected_value` |
| `min_items_check(field_value, min_count)` | Checks a list field contains at least `min_count` items |

---

## 3. New Check Definitions

### `pyQuARC/schemas/checks.json`

| Check ID | `data_type` | `check_function` | Description |
|---|---|---|---|
| `forbidden_values_check` | `string` | `forbidden_values_check` | Field must not contain placeholder/forbidden words |
| `min_length_check` | `string` | `min_length_check` | Field must meet a minimum character length |
| `regex_check` | `string` | `regex_check` | Field must match a regex pattern |
| `fields_not_equal_check` | `custom` | `fields_not_equal_check` | Two fields must not be identical |
| `required_if_check` | `custom` | `required_if_check` | Field is conditionally required based on another field's value |
| `min_items_check` | `custom` | `min_items_check` | List field must have a minimum number of items |

---

## 4. New Rules

All rules are defined in `pyQuARC/schemas/rule_mapping.json` and messages in `pyQuARC/schemas/check_messages.json`.

### Core Metadata

| Rule ID | Check ID | Severity | Formats | Description |
|---|---|---|---|---|
| `title_min_length_check` | `min_length_check` | warning | echo-c, dif10, umm-c, zenodo | Title must be at least 10 characters |
| `title_forbidden_values_check` | `forbidden_values_check` | warning | echo-c, dif10, umm-c, zenodo | Title must not contain: `test`, `sample`, `untitled`, `dataset` |
| `title_description_not_same_check` | `fields_not_equal_check` | warning | echo-c, dif10, umm-c, zenodo | Title and description must not be identical |
| `description_min_length_check` | `min_length_check` | warning | echo-c, dif10, umm-c, zenodo | Description must be at least 100 characters |
| `long_description_recommended_check` | `min_length_check` | info | echo-c, dif10, umm-c, zenodo | Description of at least 250 characters recommended |
| `version_presence_check` | `one_item_presence_check` | warning | echo-c, dif10, umm-c, zenodo | Version field must be present |

### Access & Use Constraints

| Rule ID | Check ID | Severity | Formats | Description |
|---|---|---|---|---|
| `access_constraints_presence_check` | `one_item_presence_check` | error | echo-c, dif10, umm-c, zenodo | Access constraints field must be present |
| `access_constraints_vocab_check` | `controlled_keywords_check` | error | dif10, umm-c, zenodo | Access constraints must be one of: `Public`, `Restricted`, `Internal`, `Embargoed` |
| `use_constraints_conditional_check` | `required_if_check` | error | dif10, umm-c, zenodo | Use constraints required when access constraints = `Restricted` |

### Platform & Instrument

| Rule ID | Check ID | Severity | Formats | Description |
|---|---|---|---|---|
| `collection_platform_presence_check` | `one_item_presence_check` | error | echo-c, dif10, umm-c, zenodo | At least one platform must be present |
| `platform_other_description_check` | `required_if_check` | error | echo-c, dif10, umm-c, zenodo | Platform long name required when short name = `Other` |
| `collection_instrument_presence_check` | `one_item_presence_check` | error | echo-c, dif10, umm-c, zenodo | At least one instrument must be present |
| `instrument_other_description_check` | `required_if_check` | error | echo-c, dif10, umm-c, zenodo | Instrument long name required when short name = `Other` |

### Spatial

| Rule ID | Check ID | Severity | Formats | Description |
|---|---|---|---|---|
| `spatial_reference_type_vocab_check` | `controlled_keywords_check` | warning | echo-c, dif10, umm-c, zenodo | Spatial reference type must be one of: `Geographic`, `Projected`, `UTM`, `Polar`, `Custom` |
| `spatial_resolution_presence_check` | `one_item_presence_check` | warning | echo-c, dif10, umm-c, zenodo | Spatial resolution or bounding coordinates must be present |
| `spatial_resolution_units_check` | `regex_check` | warning | umm-c, zenodo | Spatial resolution must match pattern `^[0-9]+(\.[0-9]+)?\s?(m\|km\|deg)$` (e.g. `30 m`, `1 km`, `0.25 deg`) |

### Temporal

| Rule ID | Check ID | Severity | Formats | Description |
|---|---|---|---|---|
| `temporal_resolution_vocab_check` | `controlled_keywords_check` | warning | echo-c, dif10, umm-c, zenodo | Temporal resolution must be one of: `Hourly`, `Daily`, `Weekly`, `Monthly`, `Yearly` |

### Keywords

| Rule ID | Check ID | Severity | Formats | Description |
|---|---|---|---|---|
| `science_keywords_min_count_check` | `min_items_check` | warning | echo-c, dif10, umm-c, zenodo | At least 3 keywords must be provided |

---

## 5. Zenodo Field Path Mapping

The Zenodo record structure differs from NASA CMR formats. Custom NASA fields live under `metadata.custom` (not `custom_fields`). The table below shows how each rule maps to Zenodo field paths.

| Rule | Zenodo Field Path |
|---|---|
| `title_min_length_check` | `metadata/title` |
| `title_forbidden_values_check` | `metadata/title` |
| `title_description_not_same_check` | `metadata/title`, `metadata/description` |
| `description_min_length_check` | `metadata/description` |
| `long_description_recommended_check` | `metadata/description` |
| `version_presence_check` | `metadata/version` |
| `access_constraints_presence_check` | `metadata/custom/nasa:access_constraints` |
| `access_constraints_vocab_check` | `metadata/custom/nasa:access_constraints` |
| `use_constraints_conditional_check` | `metadata/custom/nasa:use_constraints`, `metadata/custom/nasa:access_constraints` |
| `collection_platform_presence_check` | `metadata/custom/nasa:platform/id` |
| `platform_other_description_check` | `metadata/custom/nasa:platform_other`, `metadata/custom/nasa:platform/id` |
| `collection_instrument_presence_check` | `metadata/custom/nasa:instrument/id` |
| `instrument_other_description_check` | `metadata/custom/nasa:instrument_other`, `metadata/custom/nasa:instrument/id` |
| `spatial_reference_type_vocab_check` | `metadata/custom/nasa:spatial_reference_type/id` |
| `spatial_resolution_presence_check` | `metadata/custom/nasa:spatial_resolution` |
| `spatial_resolution_units_check` | `metadata/custom/nasa:spatial_resolution` |
| `temporal_resolution_vocab_check` | `metadata/custom/nasa:temporal_resolution/id` |
| `science_keywords_min_count_check` | `metadata/keywords` |

> **Note:** Zenodo vocabulary values use lowercase IDs (e.g. `"geographic"`, `"daily"`). NASA CMR formats use title-case display strings (e.g. `"Geographic"`, `"Daily"`).

---

## 6. How to Extend

### Add a value to a controlled vocabulary
Edit the `data` array in the relevant rule in `pyQuARC/schemas/rule_mapping.json`. No code changes needed.

```json
"zenodo": [
    {
        "fields": ["metadata/custom/nasa:spatial_reference_type/id"],
        "data": [["geographic", "projected", "utm", "polar", "custom", "celestial"]]
    }
]
```

### Add a new rule using an existing check
1. Add an entry to `pyQuARC/schemas/rule_mapping.json` referencing an existing `check_id`
2. Add a message entry to `pyQuARC/schemas/check_messages.json`

### Add a new check function
1. Add a `@staticmethod` to the appropriate validator class in `pyQuARC/code/`:
   - String checks → `string_validator.py` (`StringValidator`)
   - Custom/multi-field checks → `custom_validator.py` (`CustomValidator`)
   - Date/time checks → `datetime_validator.py` (`DatetimeValidator`)
   - URL checks → `url_validator.py` (`UrlValidator`)
2. Register it in `pyQuARC/schemas/checks.json`
3. Add a rule in `pyQuARC/schemas/rule_mapping.json`
4. Add a message in `pyQuARC/schemas/check_messages.json`

### Add a new metadata format
1. Add a constant in `pyQuARC/code/constants.py` and include it in `SUPPORTED_FORMATS`
2. Update the parser branch in `pyQuARC/code/checker.py` (`run()` method)
3. Update `pyQuARC/code/schema_validator.py` to handle or skip schema validation
4. Add format-specific field paths to each relevant rule in `pyQuARC/schemas/rule_mapping.json`
