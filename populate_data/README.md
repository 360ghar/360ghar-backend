# Data Populators

This folder contains scripts to seed the database with initial or sample data used during development and testing. The data population system has been redesigned with duplicate checking to prevent creating records that already exist.

## Directory Structure

```
populate_data/
├── data/                          # JSON seed files
├── data_populators/              # Populator classes with duplicate checking
├── scripts/                      # Population scripts
└── README.md                     # This file
```

## JSON Seed Files

Located in `populate_data/data/`:
- `agents.json` – Agent profiles with metadata (unique by `name`)
- `amenities.json` – Amenity definitions (unique by `title`)
- `users.json` – User accounts (unique by `email`)
- `faqs.json` – FAQ entries (unique by `question`)
- `pages.json` – CMS pages (unique by `unique_name`)
- `app_versions.json` – App version information

## Duplicate Prevention

Each populator automatically checks for existing records using unique identifiers:
- **Agents**: Skip if `name` already exists
- **Amenities**: Skip if `title` already exists
- **Users**: Skip if `email` already exists
- **FAQs**: Skip if `question` already exists (or update if `--update` flag used)
- **Pages**: Skip if `unique_name` already exists (or update if `--update` flag used)
- **Properties**: No uniqueness constraints (randomly generated test data)

## Comprehensive Loader

Populate all entities with duplicate checking:

```bash
PYTHONPATH=/path/to/backend python populate_data/scripts/load_comprehensive_data.py
```

Options:
- `--quick` – Reduced data for faster testing
- `--clear` – Clear existing data first

The loader shows counts of created vs skipped records for each entity type.

## Individual Populatos

### Agents
```bash
PYTHONPATH=/path/to/backend python populate_data/scripts/populate_agents.py
```

### Amenities
```bash
PYTHONPATH=/path/to/backend python populate_data/scripts/populate_amenities.py
```

### FAQs (with update support)
```bash
PYTHONPATH=/path/to/backend python populate_data/scripts/populate_faqs.py --update
```

### Pages (with update support)
```bash
PYTHONPATH=/path/to/backend python populate_data/scripts/populate_pages.py --update
```

## Clearing Data

Remove all test data safely:

```bash
PYTHONPATH=/path/to/backend python populate_data/scripts/clear_all_data.py --confirm
```

This clears data in reverse dependency order to avoid foreign key constraint violations.
