/**
 * Vector store field components for the Knowledge Base config modal.
 * Each component renders the fields specific to its vector store type.
 */

import { TextField } from '../FormFields';
import type { KnowledgeBaseToolConfig, KBVectorStoreType } from '../../../types/components';
import type { ValidationError } from '../ConfigurationModal';

// ============================================================================
// Shared Props
// ============================================================================

export interface VectorStoreFieldProps {
  config: KnowledgeBaseToolConfig;
  updateField: <K extends keyof KnowledgeBaseToolConfig>(field: K, value: KnowledgeBaseToolConfig[K]) => void;
  errors: ValidationError[];
}

function getError(errors: ValidationError[], field: string) {
  return errors.find((e) => e.field === field)?.message;
}

// ============================================================================
// S3 Vectors (Managed)
// ============================================================================

function VectorStoreS3VectorsFields(_props: VectorStoreFieldProps) {
  return (
    <div className="p-2.5 bg-blue-50 rounded-lg border border-blue-200">
      <p className="text-xs text-blue-700">
        Fully managed by AWS Bedrock. No configuration required. Bedrock creates and manages
        the vector index automatically.
      </p>
    </div>
  );
}

// ============================================================================
// OpenSearch Serverless
// ============================================================================

function VectorStoreOpenSearchFields({ config, updateField, errors }: VectorStoreFieldProps) {
  return (
    <>
      <div className="p-2.5 bg-amber-50 rounded-lg border border-amber-200">
        <p className="text-xs text-amber-700">
          Requires an existing OpenSearch Serverless collection with a vector index.
          The index dimensions must match your chosen embedding model.
        </p>
      </div>
      <TextField
        label="Collection ARN"
        id="kb-opensearch-collection"
        value={config.opensearchCollectionArn || ''}
        onChange={(v) => updateField('opensearchCollectionArn', v)}
        placeholder="arn:aws:aoss:us-east-1:123456789012:collection/abc123"
        required
        helpText="OpenSearch Serverless collection ARN"
        error={getError(errors, 'opensearchCollectionArn')}
      />
      <TextField
        label="Vector Index Name"
        id="kb-opensearch-index"
        value={config.opensearchVectorIndexName || 'bedrock-knowledge-base-default-index'}
        onChange={(v) => updateField('opensearchVectorIndexName', v)}
        placeholder="bedrock-knowledge-base-default-index"
        required
        error={getError(errors, 'opensearchVectorIndexName')}
      />
      <div className="grid grid-cols-3 gap-3">
        <TextField
          label="Vector Field"
          id="kb-opensearch-vector-field"
          value={config.opensearchVectorField || 'bedrock-knowledge-base-default-vector'}
          onChange={(v) => updateField('opensearchVectorField', v)}
          placeholder="bedrock-knowledge-base-default-vector"
        />
        <TextField
          label="Text Field"
          id="kb-opensearch-text-field"
          value={config.opensearchTextField || 'AMAZON_BEDROCK_TEXT_CHUNK'}
          onChange={(v) => updateField('opensearchTextField', v)}
          placeholder="AMAZON_BEDROCK_TEXT_CHUNK"
        />
        <TextField
          label="Metadata Field"
          id="kb-opensearch-metadata-field"
          value={config.opensearchMetadataField || 'AMAZON_BEDROCK_METADATA'}
          onChange={(v) => updateField('opensearchMetadataField', v)}
          placeholder="AMAZON_BEDROCK_METADATA"
        />
      </div>
    </>
  );
}

// ============================================================================
// RDS Aurora PostgreSQL (pgvector)
// ============================================================================

function VectorStoreRDSFields({ config, updateField, errors }: VectorStoreFieldProps) {
  return (
    <>
      <div className="p-2.5 bg-amber-50 rounded-lg border border-amber-200">
        <p className="text-xs text-amber-700">
          Requires an existing Aurora PostgreSQL cluster with the <span className="font-mono">pgvector</span> extension
          installed and a pre-created table with the correct schema.
        </p>
      </div>
      <TextField
        label="Cluster ARN"
        id="kb-rds-resource"
        value={config.rdsResourceArn || ''}
        onChange={(v) => updateField('rdsResourceArn', v)}
        placeholder="arn:aws:rds:us-east-1:123456789012:cluster:my-cluster"
        required
        helpText="Aurora PostgreSQL cluster ARN"
        error={getError(errors, 'rdsResourceArn')}
      />
      <TextField
        label="Credentials Secret ARN"
        id="kb-rds-secret"
        value={config.rdsCredentialsSecretArn || ''}
        onChange={(v) => updateField('rdsCredentialsSecretArn', v)}
        placeholder="arn:aws:secretsmanager:us-east-1:123456789012:secret:my-rds-creds"
        required
        helpText="Secrets Manager ARN with database username and password"
        error={getError(errors, 'rdsCredentialsSecretArn')}
      />
      <div className="grid grid-cols-2 gap-3">
        <TextField
          label="Database Name"
          id="kb-rds-database"
          value={config.rdsDatabaseName || ''}
          onChange={(v) => updateField('rdsDatabaseName', v)}
          placeholder="bedrock_kb"
          required
          error={getError(errors, 'rdsDatabaseName')}
        />
        <TextField
          label="Table Name"
          id="kb-rds-table"
          value={config.rdsTableName || ''}
          onChange={(v) => updateField('rdsTableName', v)}
          placeholder="bedrock_integration.bedrock_kb"
          required
          error={getError(errors, 'rdsTableName')}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <TextField
          label="Primary Key Field"
          id="kb-rds-pk"
          value={config.rdsPrimaryKeyField || 'id'}
          onChange={(v) => updateField('rdsPrimaryKeyField', v)}
          placeholder="id"
        />
        <TextField
          label="Vector Field"
          id="kb-rds-vector"
          value={config.rdsVectorField || 'embedding'}
          onChange={(v) => updateField('rdsVectorField', v)}
          placeholder="embedding"
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <TextField
          label="Text Field"
          id="kb-rds-text"
          value={config.rdsTextField || 'chunks'}
          onChange={(v) => updateField('rdsTextField', v)}
          placeholder="chunks"
        />
        <TextField
          label="Metadata Field"
          id="kb-rds-metadata"
          value={config.rdsMetadataField || 'metadata'}
          onChange={(v) => updateField('rdsMetadataField', v)}
          placeholder="metadata"
        />
      </div>
    </>
  );
}

// ============================================================================
// Dispatch Map
// ============================================================================

export const VECTOR_STORE_FIELDS_MAP: Record<KBVectorStoreType, React.ComponentType<VectorStoreFieldProps>> = {
  s3_vectors: VectorStoreS3VectorsFields,
  opensearch_serverless: VectorStoreOpenSearchFields,
  rds: VectorStoreRDSFields,
};
