

-- ⚠️  VARNING: Detta skript raderar ALL data i ListedInc-tabellerna.
-- Använd endast om du är helt säker. Ta gärna backup först.

BEGIN;

-- Truncate i rätt ordning. CASCADE ser till att FK hanteras.
TRUNCATE TABLE
  figure,
  asset,
  document,
  source,
  company,
  file_link,
  file_object,
  directory,
  storage_location,
  blob_store
RESTART IDENTITY CASCADE;

COMMIT;