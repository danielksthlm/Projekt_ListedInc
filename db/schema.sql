-- Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ====== Kärntabeller ======
CREATE TABLE IF NOT EXISTS company (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name             TEXT NOT NULL,
  legal_name       TEXT,
  country          TEXT,
  isin             TEXT,
  ticker           TEXT,
  website_url      TEXT,
  ir_url           TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id       UUID REFERENCES company(id) ON DELETE CASCADE,
  url              TEXT NOT NULL,
  source_type      TEXT CHECK (source_type IN ('html','pdf','image','sitemap')),
  discovered_at    TIMESTAMPTZ DEFAULT now(),
  last_fetched_at  TIMESTAMPTZ,
  http_status      INT,
  etag             TEXT,
  checksum_sha256  TEXT,
  robots_allowed   BOOLEAN,
  UNIQUE(company_id, url)
);

CREATE TABLE IF NOT EXISTS document (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id         UUID REFERENCES source(id) ON DELETE CASCADE,
  doc_type          TEXT CHECK (doc_type IN ('about','press','report','interim','governance','unknown')),
  published_at      TIMESTAMPTZ,
  title             TEXT,
  text_plain        TEXT,
  html_snapshot_url TEXT,
  pdf_blob_url      TEXT,
  lang              TEXT,
  blob_id           UUID, -- pekar ev. till blob_store.id
  created_at        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS figure (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id      UUID REFERENCES document(id) ON DELETE CASCADE,
  metric_key       TEXT,
  metric_label_raw TEXT,
  period_start     DATE,
  period_end       DATE,
  value_num        NUMERIC,
  currency         TEXT,
  unit_raw         TEXT,
  normalized_to    TEXT,
  notes            TEXT
);

CREATE TABLE IF NOT EXISTS asset (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id        UUID REFERENCES source(id) ON DELETE CASCADE,
  document_id      UUID REFERENCES document(id) ON DELETE SET NULL,
  asset_type       TEXT CHECK (asset_type IN ('image','logo','pdf_page_image')),
  url              TEXT,
  stored_url       TEXT,
  blob_id          UUID, -- pekar ev. till blob_store.id
  width            INT,
  height           INT,
  alt_text         TEXT,
  checksum_sha256  TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);

-- ====== Små binärer i DB (hybrid) ======
CREATE TABLE IF NOT EXISTS blob_store (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content_type    TEXT,
  content_length  BIGINT,
  checksum_sha256 TEXT UNIQUE,
  data            BYTEA,
  created_at      TIMESTAMPTZ DEFAULT now()
);

-- ====== Inventering av dedikerade mappar ======
CREATE TABLE IF NOT EXISTS storage_location (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  root_path   TEXT NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT now(),
  UNIQUE (root_path)
);

CREATE TABLE IF NOT EXISTS directory (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  location_id   UUID REFERENCES storage_location(id) ON DELETE CASCADE,
  rel_path      TEXT NOT NULL,
  parent_id     UUID REFERENCES directory(id) ON DELETE SET NULL,
  created_at    TIMESTAMPTZ DEFAULT now(),
  scanned_at    TIMESTAMPTZ,
  UNIQUE (location_id, rel_path)
);

CREATE TABLE IF NOT EXISTS file_object (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  directory_id  UUID REFERENCES directory(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  ext           TEXT,
  size_bytes    BIGINT NOT NULL,
  mtime         TIMESTAMPTZ NOT NULL,
  ctime         TIMESTAMPTZ,
  content_type  TEXT,
  checksum_sha256 TEXT NOT NULL,
  version_num   INT NOT NULL DEFAULT 1,
  is_current    BOOLEAN NOT NULL DEFAULT TRUE,
  is_deleted    BOOLEAN NOT NULL DEFAULT FALSE,
  category      TEXT CHECK (category IN ('pdf','html','images','other')),
  discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (directory_id, name, version_num)
);

CREATE TABLE IF NOT EXISTS file_link (
  file_id     UUID REFERENCES file_object(id) ON DELETE CASCADE,
  document_id UUID REFERENCES document(id) ON DELETE CASCADE,
  asset_id    UUID REFERENCES asset(id)    ON DELETE CASCADE,
  source_id   UUID REFERENCES source(id)   ON DELETE CASCADE,
  PRIMARY KEY (file_id, document_id, asset_id, source_id)
);

-- ====== Index ======
CREATE INDEX IF NOT EXISTS idx_document_text
  ON document USING GIN (to_tsvector('simple', coalesce(text_plain,'')));

CREATE INDEX IF NOT EXISTS idx_figure_key ON figure (metric_key, period_end);
CREATE INDEX IF NOT EXISTS idx_file_checksum ON file_object(checksum_sha256);
CREATE INDEX IF NOT EXISTS idx_file_dir_name ON file_object(directory_id, name) WHERE is_current AND NOT is_deleted;

-- ====== Hjälp- och upsert-funktioner ======
CREATE OR REPLACE FUNCTION get_or_create_directory(loc UUID, rel TEXT, parent UUID)
RETURNS UUID AS $$
DECLARE did UUID;
BEGIN
  SELECT id INTO did FROM directory WHERE location_id=loc AND rel_path=rel;
  IF did IS NULL THEN
    INSERT INTO directory(location_id, rel_path, parent_id) VALUES (loc, rel, parent) RETURNING id INTO did;
  END IF;
  RETURN did;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fileobject_demote_previous(did UUID, fname TEXT)
RETURNS VOID AS $$
BEGIN
  UPDATE file_object SET is_current=FALSE, updated_at=now()
  WHERE directory_id=did AND name=fname AND is_current=TRUE AND is_deleted=FALSE;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION upsert_file_object(
  did UUID, fname TEXT, ext TEXT, sz BIGINT, m TIMESTAMPTZ, ctype TEXT, sha TEXT
) RETURNS UUID AS $$
DECLARE fid UUID; prev_sha TEXT; prev_ver INT;
BEGIN
  SELECT id, checksum_sha256, version_num INTO fid, prev_sha, prev_ver
  FROM file_object
  WHERE directory_id=did AND name=fname AND is_current=TRUE AND is_deleted=FALSE
  ORDER BY version_num DESC LIMIT 1;

  IF fid IS NULL THEN
    INSERT INTO file_object(directory_id, name, ext, size_bytes, mtime, content_type, checksum_sha256, version_num)
    VALUES (did, fname, ext, sz, m, ctype, sha, 1)
    RETURNING id INTO fid;
    RETURN fid;
  END IF;

  IF prev_sha = sha THEN
    UPDATE file_object SET size_bytes=sz, mtime=m, content_type=ctype, updated_at=now()
    WHERE id=fid;
    RETURN fid;
  ELSE
    PERFORM fileobject_demote_previous(did, fname);
    INSERT INTO file_object(directory_id, name, ext, size_bytes, mtime, content_type, checksum_sha256, version_num)
    VALUES (did, fname, ext, sz, m, ctype, sha, prev_ver+1)
    RETURNING id INTO fid;
    RETURN fid;
  END IF;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION mark_missing_as_deleted(did UUID, present_names TEXT[])
RETURNS VOID AS $$
BEGIN
  UPDATE file_object
     SET is_deleted=TRUE, is_current=FALSE, updated_at=now()
   WHERE directory_id=did AND is_deleted=FALSE
     AND NOT (name = ANY(present_names)) AND is_current=TRUE;
END; $$ LANGUAGE plpgsql;

-- =========================
-- Metadata-kolumner för document (idempotent)
-- =========================
ALTER TABLE document ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
ALTER TABLE document ADD COLUMN IF NOT EXISTS headings JSONB;
ALTER TABLE document ADD COLUMN IF NOT EXISTS contacts JSONB;
ALTER TABLE document ADD COLUMN IF NOT EXISTS tags JSONB;
ALTER TABLE document ADD COLUMN IF NOT EXISTS checksum_sha256 TEXT;

-- Unikt per källa+innehåll (hindrar dubbletter av samma dokumentversion)
CREATE UNIQUE INDEX IF NOT EXISTS ux_document_source_checksum
  ON document (source_id, checksum_sha256);

-- Unikt på URL oavsett case
CREATE UNIQUE INDEX IF NOT EXISTS ux_source_url
  ON source ((lower(url)));

-- =========================
-- Kontakt-tabell + vy + sync-funktioner
-- =========================
-- Fristående tabell för kuraterade/normaliserade kontakter
CREATE TABLE IF NOT EXISTS contact_info (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id   UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  name          TEXT,
  role          TEXT,
  email         TEXT,
  phone_raw     TEXT,
  phone_digits  TEXT GENERATED ALWAYS AS (regexp_replace(COALESCE(phone_raw,'') , '\\D', '', 'g')) STORED,
  source        TEXT,  -- 'html','pdf','inferred'
  created_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE (document_id, COALESCE(email,''), COALESCE(phone_digits,''))
);

-- Sökindex
CREATE INDEX IF NOT EXISTS ix_contact_info_document_id ON contact_info(document_id);
CREATE INDEX IF NOT EXISTS ix_contact_info_email_lower ON contact_info((lower(email)));
CREATE INDEX IF NOT EXISTS ix_contact_info_phone_digits ON contact_info(phone_digits);

-- Vy som plattar ut JSON-kontakter i document till rader (read-only)
CREATE OR REPLACE VIEW contact_info_extracted AS
WITH base AS (
  SELECT d.id AS document_id, d.contacts
  FROM document d
  WHERE d.contacts IS NOT NULL AND jsonb_typeof(d.contacts) = 'object'
)
-- people
SELECT
  b.document_id,
  (p->>'name')::TEXT      AS name,
  (p->>'role')::TEXT      AS role,
  (p->>'email')::TEXT     AS email,
  NULL::TEXT              AS phone_raw,
  regexp_replace(COALESCE((p->>'phone')::TEXT,''),'\\D','','g') AS phone_digits,
  'people'::TEXT          AS source
FROM base b
CROSS JOIN LATERAL jsonb_path_query(b.contacts, '$.people[*]') AS p
UNION ALL
-- emails
SELECT
  b.document_id,
  NULL::TEXT,
  NULL::TEXT,
  e::TEXT AS email,
  NULL::TEXT,
  NULL::TEXT,
  'emails'::TEXT
FROM base b
CROSS JOIN LATERAL jsonb_path_query_array(b.contacts, '$.emails') AS e
UNION ALL
-- phones
SELECT
  b.document_id,
  NULL::TEXT,
  NULL::TEXT,
  NULL::TEXT,
  ph::TEXT AS phone_raw,
  regexp_replace(COALESCE(ph::TEXT,''),'\\D','','g') AS phone_digits,
  'phones'::TEXT
FROM base b
CROSS JOIN LATERAL jsonb_path_query_array(b.contacts, '$.phones') AS ph;

-- Funktion: synka contact_info från document.contacts för ett dokument
CREATE OR REPLACE FUNCTION sync_contact_info_from_document(p_document_id UUID)
RETURNS VOID AS $$
BEGIN
  -- Ta bort tidigare rader för dokumentet (vi genererar på nytt)
  DELETE FROM contact_info WHERE document_id = p_document_id;

  -- people
  INSERT INTO contact_info (document_id, name, role, email, phone_raw, source)
  SELECT
    d.id,
    (p->>'name')::TEXT,
    (p->>'role')::TEXT,
    (p->>'email')::TEXT,
    NULL::TEXT,
    'people'
  FROM document d
  CROSS JOIN LATERAL jsonb_path_query(d.contacts, '$.people[*]') AS p
  WHERE d.id = p_document_id
    AND d.contacts IS NOT NULL
    AND jsonb_typeof(d.contacts) = 'object';

  -- emails
  INSERT INTO contact_info (document_id, email, source)
  SELECT d.id, e::TEXT, 'emails'
  FROM document d
  CROSS JOIN LATERAL jsonb_path_query_array(d.contacts, '$.emails') AS e
  WHERE d.id = p_document_id
    AND d.contacts IS NOT NULL
    AND jsonb_typeof(d.contacts) = 'object'
    AND (e::TEXT) IS NOT NULL
  ON CONFLICT (document_id, COALESCE(email,''), COALESCE(phone_digits,'')) DO NOTHING;

  -- phones
  INSERT INTO contact_info (document_id, phone_raw, source)
  SELECT d.id, ph::TEXT, 'phones'
  FROM document d
  CROSS JOIN LATERAL jsonb_path_query_array(d.contacts, '$.phones') AS ph
  WHERE d.id = p_document_id
    AND d.contacts IS NOT NULL
    AND jsonb_typeof(d.contacts) = 'object'
    AND (ph::TEXT) IS NOT NULL
  ON CONFLICT (document_id, COALESCE(email,''), COALESCE(phone_digits,'')) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

-- Funktion: synka alla dokument
CREATE OR REPLACE FUNCTION sync_all_contact_info()
RETURNS VOID AS $$
DECLARE r RECORD;
BEGIN
  FOR r IN SELECT id FROM document LOOP
    PERFORM sync_contact_info_from_document(r.id);
  END LOOP;
END;
$$ LANGUAGE plpgsql;