-- Compatibility patch for older DBs where SchemaRelationship used `rel_id`
-- and didn't include edge_property_source_fields.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'schemarelationship'
          AND column_name = 'rel_id'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'schemarelationship'
          AND column_name = 'relationship_id'
    ) THEN
        ALTER TABLE SchemaRelationship RENAME COLUMN rel_id TO relationship_id;
    END IF;
END $$;

ALTER TABLE SchemaRelationship
ADD COLUMN IF NOT EXISTS edge_property_source_fields TEXT;
