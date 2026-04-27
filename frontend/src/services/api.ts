/**
 * API Client Service for backend integration.
 * Implements workflow CRUD operations, validation calls, and deployment calls.
 * Requirements: 9.1, 11.1
 */

import type { WorkflowDefinition, DeploymentStatus } from '../types/workflow';
import type { ValidationResult } from '../types/validation';
import type { Flow, FlowCreateRequest, FlowUpdateRequest, FlowResponse, FlowListResponse } from '../types/flow';
import { authFetch } from '../auth/authFetch';

// ============================================================================
// Configuration
// ============================================================================

/**
 * Base URL for the backend API.
 * Can be configured via environment variable.
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

// ============================================================================
// Types
// ============================================================================

export interface ApiError {
  message: string;
  status: number;
  details?: unknown;
}

export interface WorkflowCreateRequest {
  name: string;
  description?: string;
  version?: string;
  nodes?: unknown[];
  edges?: unknown[];
  viewport?: {
    x: number;
    y: number;
    zoom: number;
  };
  metadata: {
    author: string;
    tags?: string[];
    awsRegion: string;
    deploymentStatus?: DeploymentStatus;
  };
}

export interface WorkflowUpdateRequest {
  name?: string;
  description?: string;
  version?: string;
  nodes?: unknown[];
  edges?: unknown[];
  viewport?: {
    x: number;
    y: number;
    zoom: number;
  };
  metadata?: {
    author: string;
    tags?: string[];
    awsRegion: string;
    deploymentStatus?: DeploymentStatus;
  };
}

export interface WorkflowResponse {
  workflow: WorkflowDefinition;
  message: string;
}

export interface DeleteResponse {
  success: boolean;
  message: string;
}

export interface DeployRequest {
  aws_region: string;
  vpc_config?: Record<string, unknown>;
  enable_cloudwatch?: boolean;
  enable_cloudtrail?: boolean;
}

export interface DeploymentResult {
  deployment_id: string;
  status: 'success' | 'failed' | 'in_progress';
  endpoint_url?: string;
  error_message?: string;
  created_resources: string[];
}

export interface ImportRequest {
  workflow_json: Record<string, unknown>;
}

export interface ImportResponse {
  workflow: WorkflowDefinition;
  message: string;
  validation_errors: string[];
}

export interface ExportResponse {
  workflow_json: Record<string, unknown>;
  message: string;
}

// ============================================================================
// API Client Class
// ============================================================================

export class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  // ==========================================================================
  // Private Helper Methods
  // ==========================================================================

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;

    const defaultHeaders: HeadersInit = {
      'Content-Type': 'application/json',
    };

    const response = await authFetch(url, {
      ...options,
      headers: {
        ...defaultHeaders,
        ...options.headers,
      },
    });

    if (!response.ok) {
      let errorDetails: unknown;
      try {
        errorDetails = await response.json();
      } catch {
        errorDetails = await response.text();
      }

      const error: ApiError = {
        message: this.extractErrorMessage(errorDetails, response.statusText),
        status: response.status,
        details: errorDetails,
      };
      throw error;
    }

    // Guard against non-JSON responses (e.g., CloudFront returning HTML for 404s)
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      const text = await response.text();
      const error: ApiError = {
        message: 'Unexpected response from server',
        status: response.status,
        details: text,
      };
      throw error;
    }

    return response.json() as Promise<T>;
  }

  private extractErrorMessage(details: unknown, fallback: string): string {
    if (typeof details === 'string') {
      return details;
    }
    if (typeof details === 'object' && details !== null) {
      const obj = details as Record<string, unknown>;
      if (typeof obj.detail === 'string') {
        return obj.detail;
      }
      if (typeof obj.message === 'string') {
        return obj.message;
      }
      if (typeof obj.detail === 'object' && obj.detail !== null) {
        const detailObj = obj.detail as Record<string, unknown>;
        if (typeof detailObj.message === 'string') {
          return detailObj.message;
        }
        if (Array.isArray(detailObj.errors)) {
          return detailObj.errors.join(', ');
        }
      }
    }
    return fallback;
  }

  // ==========================================================================
  // Health Check
  // ==========================================================================

  /**
   * Checks if the backend API is healthy.
   */
  async healthCheck(): Promise<{ status: string }> {
    return this.request<{ status: string }>('/health');
  }

  // ==========================================================================
  // Workflow CRUD Operations
  // ==========================================================================

  /**
   * Creates a new workflow.
   * Requirement 9.1: Auto-save workflow
   */
  async createWorkflow(data: WorkflowCreateRequest): Promise<WorkflowResponse> {
    return this.request<WorkflowResponse>('/api/workflows', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Gets a workflow by ID.
   * Requirement 9.5: Restore last saved workflow
   */
  async getWorkflow(workflowId: string): Promise<WorkflowDefinition> {
    return this.request<WorkflowDefinition>(`/api/workflows/${workflowId}`);
  }

  /**
   * Updates an existing workflow.
   * Requirement 9.1: Auto-save workflow
   */
  async updateWorkflow(
    workflowId: string,
    data: WorkflowUpdateRequest
  ): Promise<WorkflowResponse> {
    return this.request<WorkflowResponse>(`/api/workflows/${workflowId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * Deletes a workflow by ID.
   */
  async deleteWorkflow(workflowId: string): Promise<DeleteResponse> {
    return this.request<DeleteResponse>(`/api/workflows/${workflowId}`, {
      method: 'DELETE',
    });
  }

  // ==========================================================================
  // Validation
  // ==========================================================================

  /**
   * Validates a workflow configuration.
   * Requirements: 8.1, 8.2, 8.3
   */
  async validateWorkflow(workflowId: string): Promise<ValidationResult> {
    return this.request<ValidationResult>(`/api/workflows/${workflowId}/validate`, {
      method: 'POST',
    });
  }

  // ==========================================================================
  // Import/Export
  // ==========================================================================

  /**
   * Imports a workflow from JSON.
   * Requirements: 14.1, 14.2, 14.3
   */
  async importWorkflow(data: ImportRequest): Promise<ImportResponse> {
    return this.request<ImportResponse>('/api/workflows/import', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Exports a workflow as JSON.
   * Requirements: 14.1, 14.2
   */
  async exportWorkflow(workflowId: string): Promise<ExportResponse> {
    return this.request<ExportResponse>(`/api/workflows/${workflowId}/export`);
  }

  // ==========================================================================
  // Flow CRUD Operations
  // ==========================================================================

  /**
   * Creates a new flow.
   */
  async createFlow(data: FlowCreateRequest): Promise<FlowResponse> {
    return this.request<FlowResponse>('/api/flows', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Lists all flows.
   */
  async listFlows(): Promise<FlowListResponse> {
    return this.request<FlowListResponse>('/api/flows');
  }

  /**
   * Gets a flow by ID.
   */
  async getFlow(flowId: string): Promise<Flow> {
    return this.request<Flow>(`/api/flows/${flowId}`);
  }

  /**
   * Updates an existing flow.
   */
  async updateFlow(
    flowId: string,
    data: FlowUpdateRequest
  ): Promise<FlowResponse> {
    return this.request<FlowResponse>(`/api/flows/${flowId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * Deletes a flow by ID.
   */
  async deleteFlow(flowId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/api/flows/${flowId}`, {
      method: 'DELETE',
    });
  }

  // ==========================================================================
  // Deployment
  // ==========================================================================

  /**
   * Deploys a workflow to AWS.
   * Requirements: 11.1, 11.5, 11.6, 11.7
   */
  async deployWorkflow(
    workflowId: string,
    config: DeployRequest
  ): Promise<DeploymentResult> {
    return this.request<DeploymentResult>(`/api/workflows/${workflowId}/deploy`, {
      method: 'POST',
      body: JSON.stringify(config),
    });
  }
}

// ============================================================================
// Singleton Instance
// ============================================================================

let apiClientInstance: ApiClient | null = null;

/**
 * Gets the singleton ApiClient instance.
 */
export function getApiClient(): ApiClient {
  if (!apiClientInstance) {
    apiClientInstance = new ApiClient();
  }
  return apiClientInstance;
}

/**
 * Resets the singleton instance (for testing).
 */
export function resetApiClient(): void {
  apiClientInstance = null;
}

/**
 * Creates a new ApiClient instance with custom base URL.
 */
export function createApiClient(baseUrl?: string): ApiClient {
  return new ApiClient(baseUrl);
}

// ============================================================================
// Type Guards
// ============================================================================

/**
 * Type guard to check if an error is an ApiError.
 */
export function isApiError(error: unknown): error is ApiError {
  return (
    typeof error === 'object' &&
    error !== null &&
    'message' in error &&
    'status' in error &&
    typeof (error as ApiError).message === 'string' &&
    typeof (error as ApiError).status === 'number'
  );
}

/**
 * Extracts error message from any error type.
 */
export function getErrorMessage(error: unknown): string {
  if (isApiError(error)) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === 'string') {
    return error;
  }
  return 'An unknown error occurred';
}

// ============================================================================
// AI Tool Generator Types
// ============================================================================

export interface ToolGenerateRequest {
  prompt: string;
  conversationHistory?: Array<{ role: string; content: string }>;
  existingTool?: Record<string, unknown>;
}

export interface GeneratedTool {
  toolName: string;
  displayName: string;
  description: string;
  lambdaCode: string;
  inputSchema: Record<string, unknown>;
}

export interface ToolGenerateResponse {
  success: boolean;
  tool?: GeneratedTool;
  message: string;
  error?: string;
  responseType?: 'clarification' | 'generation';
  testCases?: TestCase[];
}

// ============================================================================
// AI Tool Testing Types
// ============================================================================

export interface TestCase {
  name: string;
  input: Record<string, unknown>;
  expectedOutputKeys: string[];
  description: string;
}

export interface TestResult {
  testCaseName: string;
  passed: boolean;
  actualOutput?: Record<string, unknown>;
  error?: string;
  durationMs: number;
}

export interface ToolTestRequest {
  lambdaCode: string;
  testCases: TestCase[];
}

export interface ToolTestResponse {
  success: boolean;
  results: TestResult[];
  allPassed: boolean;
  error?: string;
}

// ============================================================================
// AI Tool Generator API Function
// ============================================================================

/**
 * Generate a Lambda tool using AI from a natural language description.
 * Calls POST /api/generate-tool on the deployment API.
 *
 * - Clarification mode (no history): synchronous response
 * - Generation mode (has history): async — returns jobId, polls until complete
 */
export async function generateToolApi(
  data: ToolGenerateRequest,
  baseUrl: string = API_BASE_URL,
): Promise<ToolGenerateResponse> {
  const url = `${baseUrl}/api/generate-tool`;
  const response = await authFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const err = await response.json();
      detail = err.detail || err.message || detail;
    } catch {
      // ignore parse errors
    }
    return { success: false, message: '', error: `Request failed (${response.status}): ${detail}` };
  }

  const result = await response.json();

  // Async mode: generation returns {jobId, status: "running"}
  if (result.jobId && result.status === 'running') {
    return pollGenerateJob(result.jobId, baseUrl);
  }

  // Sync mode: clarification returns ToolGenerateResponse directly
  return result as ToolGenerateResponse;
}

async function pollGenerateJob(
  jobId: string,
  baseUrl: string,
  maxAttempts: number = 40,
  intervalMs: number = 2000,
): Promise<ToolGenerateResponse> {
  const pollUrl = `${baseUrl}/api/generate-tool/${jobId}`;

  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    try {
      const resp = await authFetch(pollUrl);
      if (!resp.ok) continue;
      const data = await resp.json();
      if (data.status === 'running') continue;
      // Completed — map to ToolGenerateResponse
      return data as ToolGenerateResponse;
    } catch {
      // Network error — retry
    }
  }

  return { success: false, message: '', error: 'Tool generation timed out after 80 seconds' };
}

// ============================================================================
// AI Tool Testing API Function
// ============================================================================

/**
 * Test a generated Lambda tool by deploying it temporarily and running test cases.
 * Calls POST /api/test-tool on the deployment API.
 */
/**
 * Test a generated Lambda tool using async polling.
 * POST starts the test (returns testId), then polls GET until complete.
 * This avoids the API Gateway 30s timeout for long-running tests.
 */
export async function testToolApi(
  data: ToolTestRequest,
  baseUrl: string = API_BASE_URL,
): Promise<ToolTestResponse> {
  // Step 1: Start async test
  const startUrl = `${baseUrl}/api/test-tool`;
  const startResponse = await authFetch(startUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

  if (!startResponse.ok) {
    let detail = startResponse.statusText;
    try {
      const err = await startResponse.json();
      detail = err.detail || err.message || detail;
    } catch { /* ignore */ }
    return { success: false, results: [], allPassed: false, error: `Request failed (${startResponse.status}): ${detail}` };
  }

  const { testId } = await startResponse.json() as { testId: string };

  // Step 2: Poll for results (every 3s, up to 2 minutes)
  const pollUrl = `${baseUrl}/api/test-tool/${testId}`;
  const maxAttempts = 40;
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(r => setTimeout(r, 3000));

    try {
      const pollResponse = await authFetch(pollUrl);
      if (!pollResponse.ok) continue;

      const result = await pollResponse.json() as { status: string; success?: boolean; allPassed?: boolean; results?: TestResult[]; error?: string };
      if (result.status === 'running') continue;

      // Test completed
      return {
        success: result.success ?? false,
        allPassed: result.allPassed ?? false,
        results: result.results ?? [],
        error: result.error,
      };
    } catch {
      // Network error, retry
      continue;
    }
  }

  return { success: false, results: [], allPassed: false, error: 'Test timed out after 2 minutes' };
}

export default ApiClient;
