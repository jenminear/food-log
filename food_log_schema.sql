-- ============================================================
-- Food Log Database Schema
-- ============================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ------------------------------------------------------------
-- RECIPES
-- Stores recipe definitions: steps, timing, dietary flags, source
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recipes (
    recipe_id           INTEGER PRIMARY KEY AUTOINCREMENT,   -- [R]
    recipe_name         VARCHAR(255) NOT NULL,
    picture_path        TEXT,                                -- file path to stored image (e.g. "images/recipes/42.jpg")
    steps_txt           TEXT,
    num_servings        REAL,                                -- float(2)
    active_time_mins    INTEGER,                             -- active cook time in whole minutes
    total_time_mins     INTEGER,                             -- total time in whole minutes (incl. passive)
    need_oven           INTEGER NOT NULL DEFAULT 0           -- 0 = no, 1 = yes
                            CHECK (need_oven IN (0, 1)),
    vegan               INTEGER NOT NULL DEFAULT 0
                            CHECK (vegan IN (0, 1)),
    vegetarian          INTEGER NOT NULL DEFAULT 0
                            CHECK (vegetarian IN (0, 1)),
    source              TEXT                                 -- URL or file path to source (recipe card photo, website, etc.)
);

-- ------------------------------------------------------------
-- INGREDIENTS
-- Master ingredient list with nutrition info per 100g.
-- All nutrition columns are per 100g of the ingredient.
-- Portion fields capture a typical serving size from USDA/OFF,
-- used to convert recipe units (e.g. "2 cups") to grams.
--
-- Nutrition calculation in components:
--   nutrient = quantity_multiple × (portion_grams / 100) × nutrient_per_100g
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingredients (
    ingredient_id           INTEGER PRIMARY KEY AUTOINCREMENT,  -- [R]
    ingredient_name         VARCHAR(255) NOT NULL,              -- user-facing label (not unique - multiple
                                                                 -- ingredients may share a label, e.g. "apple"
                                                                 -- for both a medium and a large apple)
    source_food_name        VARCHAR(255),                       -- canonical food name from USDA/OFF, if any;
                                                                 -- combined with portion_unit this determines
                                                                 -- de-duplication for USDA/OFF-sourced ingredients
    portion_unit            VARCHAR(50) NOT NULL DEFAULT 'g',   -- full portion description e.g. "1 cup", "1 medium stalk"
    portion_grams           REAL    NOT NULL DEFAULT 100.0,     -- grams per one portion e.g. 90.0
    protein_grams           REAL,                               -- per 100g
    fat_grams               REAL,                               -- per 100g
    carb_grams              REAL,                               -- per 100g
    fiber_grams             REAL,                               -- per 100g
    calories                REAL,                               -- per 100g
    nutrition_info_source   VARCHAR(500)                        -- URL or identifier of data source
);

-- ------------------------------------------------------------
-- BATCHES
-- A specific cook of a recipe on a given date
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS batches (
    batch_id        INTEGER PRIMARY KEY AUTOINCREMENT,  -- [R]
    recipe_id       INTEGER NOT NULL,                   -- [R]
    date            TEXT    NOT NULL,                   -- [R] ISO-8601: YYYY-MM-DD
    picture_path    TEXT,                               -- file path to optional photo of the batch (e.g. "images/batches/7.jpg")
    recipe_changes  INTEGER NOT NULL DEFAULT 0          -- [R] 0 = no changes, 1 = changes made
                        CHECK (recipe_changes IN (0, 1)),

    FOREIGN KEY (recipe_id) REFERENCES recipes (recipe_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ------------------------------------------------------------
-- COMPONENTS
-- Links an ingredient to a recipe, batch, or meal (snack)
-- Exactly one of recipe_id / batch_id / meal_id should be set
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS components (
    component_id        INTEGER PRIMARY KEY AUTOINCREMENT,  -- [R]
    recipe_id           INTEGER,                            -- set for recipe-level components
    batch_id            INTEGER,                            -- set for batch-level overrides
    meal_id             INTEGER,                            -- set for standalone meal ingredients
    ingredient_id       INTEGER NOT NULL,                   -- [R]
    quantity_multiple   REAL    NOT NULL,                   -- [R] multiplier on base_quantity

    -- Enforce that exactly one parent FK is set
    CHECK (
        (recipe_id IS NOT NULL) + (batch_id IS NOT NULL) + (meal_id IS NOT NULL) = 1
    ),

    FOREIGN KEY (recipe_id)     REFERENCES recipes      (recipe_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (batch_id)      REFERENCES batches      (batch_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (ingredient_id) REFERENCES ingredients  (ingredient_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
    -- meal_id FK added after meals table creation (see trigger comment below)
);

-- ------------------------------------------------------------
-- MEALS
-- A single eating event linked to a batch or standalone components
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meals (
    meal_id             INTEGER PRIMARY KEY AUTOINCREMENT,  -- [R]
    meal_type           TEXT    NOT NULL                    -- [R]
                            CHECK (meal_type IN (
                                'breakfast',
                                'lunch',
                                'dinner',
                                'morning_snack',
                                'afternoon_snack',
                                'evening_snack'
                            )),
    date                TEXT    NOT NULL,                   -- [R] ISO-8601: YYYY-MM-DD
    timestamp           INTEGER,                            -- Unix timestamp (seconds since 1970-01-01 UTC) of when the meal was eaten
    fraction_of_batch   REAL,                               -- what fraction of the batch was eaten
    batch_id            INTEGER,                            -- NULL if standalone ingredient meal

    FOREIGN KEY (batch_id) REFERENCES batches (batch_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- Now that meals exists, add the FK from components → meals
-- SQLite doesn't support ALTER TABLE ADD CONSTRAINT, so the FK is declared
-- in the components table definition above but enforced via the trigger below.

CREATE TRIGGER IF NOT EXISTS fk_components_meal_id
BEFORE INSERT ON components
FOR EACH ROW
WHEN NEW.meal_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Foreign key violation: meal_id not found in meals')
    WHERE NOT EXISTS (
        SELECT 1 FROM meals WHERE meal_id = NEW.meal_id
    );
END;

-- ------------------------------------------------------------
-- NOTES
-- Free-text notes attachable to a recipe, batch, or meal
-- At least one of recipe_id / batch_id / meal_id should be set
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notes (
    note_id     INTEGER PRIMARY KEY AUTOINCREMENT,  -- [R]
    note_date   TEXT    NOT NULL,                   -- [R] ISO-8601: YYYY-MM-DD
    recipe_id   INTEGER,
    batch_id    INTEGER,
    meal_id     INTEGER,
    note_txt    TEXT    NOT NULL,                   -- [R]

    FOREIGN KEY (recipe_id) REFERENCES recipes  (recipe_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (batch_id)  REFERENCES batches  (batch_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (meal_id)   REFERENCES meals    (meal_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

-- ============================================================
-- INDEXES  (for common query patterns)
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_batches_recipe_id      ON batches    (recipe_id);
CREATE INDEX IF NOT EXISTS idx_batches_date           ON batches    (date);
CREATE INDEX IF NOT EXISTS idx_components_recipe_id   ON components (recipe_id);
CREATE INDEX IF NOT EXISTS idx_components_batch_id    ON components (batch_id);
CREATE INDEX IF NOT EXISTS idx_components_meal_id     ON components (meal_id);
CREATE INDEX IF NOT EXISTS idx_components_ingredient  ON components (ingredient_id);
CREATE INDEX IF NOT EXISTS idx_meals_date             ON meals      (date);
CREATE INDEX IF NOT EXISTS idx_meals_batch_id         ON meals      (batch_id);
CREATE INDEX IF NOT EXISTS idx_notes_recipe_id        ON notes      (recipe_id);
CREATE INDEX IF NOT EXISTS idx_notes_batch_id         ON notes      (batch_id);
CREATE INDEX IF NOT EXISTS idx_notes_meal_id          ON notes      (meal_id);
CREATE INDEX IF NOT EXISTS idx_notes_date             ON notes      (note_date);
