import { useState, useCallback, useEffect } from 'react';
import { signOut } from 'aws-amplify/auth';
import WorkflowCanvas from './components/canvas/WorkflowCanvas';
import { ComponentPalette } from './components/palette/ComponentPalette';
import { RuntimeConfigurationModal } from './components/modals/RuntimeConfigurationModal';
import { GatewayConfigurationModal } from './components/modals/GatewayConfigurationModal';
import { IdentityConfigurationModal } from './components/modals/IdentityConfigurationModal';
import { DeployPanel } from './components/deploy/DeployPanel';
import { ActiveDeploymentBanner } from './components/deploy/ActiveDeploymentBanner';
import type { ActiveDeployment } from './components/deploy/ActiveDeploymentBanner';
import { ToolGeneratorPanel } from './components/ai/ToolGeneratorPanel';
import { TemplateGallery } from './components/templates';
import { MemoryConfigurationModal } from './components/modals/MemoryConfigurationModal';
import { PolicyConfigurationModal } from './components/modals/PolicyConfigurationModal';
import { KnowledgeBaseConfigModal } from './components/modals/KnowledgeBaseConfigModal';
import { GuardrailsConfigurationModal } from './components/modals/GuardrailsConfigurationModal';
import { ApprovalInbox } from './components/approvals/ApprovalInbox';
import { approvalStats } from './services/approvals';
import HarnessManager from './components/harness/HarnessManager';
import AgentCoreManager from './components/agentcore/AgentCoreManager';
import { AnimatePresence, motion } from 'framer-motion';
import { useWorkflowStore } from './store/workflowStore';
import { useFlowStore } from './store/flowStore';
import { useAutoSave } from './hooks/useAutoSave';
import { instantiateTemplate } from './utils/templates';
import type { AgentCoreComponentType } from './types/workflow';
import type { WorkflowTemplate } from './types/templates';
import type { RuntimeConfiguration, GatewayConfiguration, IdentityConfiguration, MemoryConfiguration, PolicyConfiguration, GuardrailsConfiguration, ComponentConfiguration, ToolConfiguration, KnowledgeBaseToolConfig } from './types/components';
import type { GeneratedTool } from './services/api';
import './App.css';

function App() {
  const { activeFlowId, activeFlowName } = useFlowStore();

  // Auto-save active flow workflow (only saves when activeFlowId is set)
  useAutoSave(activeFlowId);

  const [paletteCollapsed, setPaletteCollapsed] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [showDeployPanel, setShowDeployPanel] = useState(false);
  const [showTemplateGallery, setShowTemplateGallery] = useState(false);
  const [showToolGenerator, setShowToolGenerator] = useState(false);
  const [showApprovalInbox, setShowApprovalInbox] = useState(false);
  const [pendingApprovalCount, setPendingApprovalCount] = useState<number>(0);
  const [showHarnessManager, setShowHarnessManager] = useState(false);
  const [showAgentCoreManager, setShowAgentCoreManager] = useState(false);
  const [restoredDeployment, setRestoredDeployment] = useState<{
    runtimeId: string;
    endpoint: string;
    gatewayUrl?: string;
  } | null>(null);

  const handleRestoreDeployment = useCallback((deployment: ActiveDeployment) => {
    setRestoredDeployment({
      runtimeId: deployment.runtime_id || deployment.deployment_id,
      endpoint: deployment.runtime_endpoint || '',
      gatewayUrl: deployment.gateway_url,
    });
    setShowDeployPanel(true);
  }, []);

  // Modal state
  const [configModal, setConfigModal] = useState<{
    isOpen: boolean;
    nodeId: string | null;
    componentType: AgentCoreComponentType | null;
    initialConfig?: ComponentConfiguration;
  }>({ isOpen: false, nodeId: null, componentType: null });

  // Pending node creation (to open modal after node is added)
  const [pendingNodeConfig, setPendingNodeConfig] = useState<{
    componentType: AgentCoreComponentType;
    position: { x: number; y: number };
  } | null>(null);

  const { nodes, edges, updateNodeConfiguration, selectedNodeId, runValidation, loadTemplate, activeTemplateId, addNode } = useWorkflowStore();

  // Get selected runtime node for deployment
  const selectedNode = selectedNodeId ? nodes.find((n) => n.id === selectedNodeId) : null;
  const selectedRuntimeConfig = selectedNode?.data.componentType === 'runtime'
    ? selectedNode.data.configuration as RuntimeConfiguration
    : null;

  // Find first HTTP-protocol runtime node if none selected.
  // Prefer HTTP runtimes over MCP runtimes — the MCP server is a target, not the deployable agent.
  // Also exclude runtime nodes that are MCP server targets (connected to a gateway alongside another runtime).
  const mcpServerNodeIds = new Set<string>();
  // Detect multi-runtime-gateway pattern: if a gateway has 2+ runtimes connected, the non-agent ones are MCP servers.
  const gatewayNodes = nodes.filter((n) => n.data.componentType === 'gateway');
  for (const gw of gatewayNodes) {
    const connectedRuntimeIds = edges
      .filter((e) => e.source === gw.id || e.target === gw.id)
      .map((e) => (e.source === gw.id ? e.target : e.source))
      .filter((nid) => nodes.find((n) => n.id === nid)?.data.componentType === 'runtime');
    if (connectedRuntimeIds.length >= 2) {
      // Multiple runtimes on one gateway — identify which is the MCP server.
      // Prefer the runtime with protocol=MCP as the server. If none, pick the one with fewer total connections.
      const runtimeInfos = connectedRuntimeIds.map((rid) => {
        const rn = nodes.find((n) => n.id === rid)!;
        const cfg = rn.data.configuration as RuntimeConfiguration | undefined;
        const totalEdges = edges.filter((e) => e.source === rid || e.target === rid).length;
        return { id: rid, protocol: cfg?.protocol || 'HTTP', totalEdges };
      });
      // First pass: any with MCP protocol is the server
      const mcpOnes = runtimeInfos.filter((r) => r.protocol === 'MCP');
      if (mcpOnes.length > 0) {
        mcpOnes.forEach((r) => mcpServerNodeIds.add(r.id));
      } else {
        // Both HTTP: the one with fewer connections is likely the MCP server (agent has more connections: identity, memory, etc.)
        const sorted = [...runtimeInfos].sort((a, b) => a.totalEdges - b.totalEdges);
        // Mark all except the one with most connections as MCP servers
        sorted.slice(0, -1).forEach((r) => mcpServerNodeIds.add(r.id));
      }
    }
  }

  const firstRuntimeNode = nodes.find((n) => {
    if (n.data.componentType !== 'runtime') return false;
    if (mcpServerNodeIds.has(n.id)) return false; // Exclude MCP server targets
    const cfg = n.data.configuration as RuntimeConfiguration | undefined;
    return !cfg || cfg.protocol !== 'MCP';
  }) || nodes.find((n) => n.data.componentType === 'runtime' && !mcpServerNodeIds.has(n.id))
     || nodes.find((n) => n.data.componentType === 'runtime');
  const deployableConfig = selectedRuntimeConfig || (firstRuntimeNode?.data.configuration as RuntimeConfiguration | undefined);
  // Always use the runtime node's ID (not a selected non-runtime node like a gateway)
  const deployableNodeId = (selectedRuntimeConfig ? selectedNodeId : null) || firstRuntimeNode?.id || null;

  // Get connected tools, gateway config, identity config, custom tools, and MCP server config
  const getConnectedToolsAndGateway = useCallback(() => {
    if (!deployableNodeId) return { tools: [], gatewayConfig: null, gatewayTools: [], identityConfig: null, customTools: [], memoryConfig: null, evaluationConfig: null, policyConfig: null, guardrailsConfig: null, mcpServerConfig: null, knowledgeBaseConfig: null };
    const connectedTools: string[] = [];
    const gatewayTools: string[] = [];
    let gatewayConfig = null;
    let gatewayNodeId: string | null = null;
    let identityConfig: IdentityConfiguration | null = null;
    let memoryConfig: Record<string, unknown> | null = null;
    let evaluationConfig: Record<string, unknown> | null = null;
    let policyConfig: Record<string, unknown> | null = null;
    let guardrailsConfig: Record<string, unknown> | null = null;
    let mcpServerConfig: Record<string, unknown> | null = null;

    // Find direct connections to the runtime node
    edges.forEach(edge => {
      if (edge.source === deployableNodeId || edge.target === deployableNodeId) {
        const otherNodeId = edge.source === deployableNodeId ? edge.target : edge.source;
        const otherNode = nodes.find(n => n.id === otherNodeId);
        if (otherNode) {
          const type = otherNode.data.componentType;
          if (['browser', 'code_interpreter', 'memory', 'gateway', 'identity', 'observability', 'evaluation', 'policy', 'guardrails'].includes(type)) {
            connectedTools.push(type);
            if (type === 'gateway' && otherNode.data.configuration) {
              gatewayConfig = otherNode.data.configuration;
              gatewayNodeId = otherNode.id;
            }
            if (type === 'identity' && otherNode.data.configuration) {
              identityConfig = otherNode.data.configuration as IdentityConfiguration;
            }
            if (type === 'memory') {
              memoryConfig = (otherNode.data.configuration as unknown as Record<string, unknown>) || { enabled: true };
            }
            if (type === 'evaluation') {
              evaluationConfig = (otherNode.data.configuration as unknown as Record<string, unknown>) || { enabled: true };
            }
            if (type === 'observability' && !evaluationConfig) {
              evaluationConfig = (otherNode.data.configuration as unknown as Record<string, unknown>) || { enabled: false };
            }
            if (type === 'policy') {
              policyConfig = (otherNode.data.configuration as unknown as Record<string, unknown>) || { enabled: true };
            }
            if (type === 'guardrails') {
              guardrailsConfig = (otherNode.data.configuration as unknown as Record<string, unknown>) || { enabled: true };
            }
          }
        }
      }
    });

    // Find tool nodes and MCP Server Runtime nodes connected to the gateway
    const customTools: Array<{ toolName: string; displayName: string; description: string; lambdaCode: string; inputSchema: Record<string, unknown> }> = [];
    let knowledgeBaseConfig: Record<string, unknown> | null = null;
    const mcpServerTools: string[] = [];
    if (gatewayNodeId) {
      edges.forEach(edge => {
        if (edge.source === gatewayNodeId || edge.target === gatewayNodeId) {
          const otherNodeId = edge.source === gatewayNodeId ? edge.target : edge.source;
          // Skip the main deployable runtime
          if (otherNodeId === deployableNodeId) return;
          const otherNode = nodes.find(n => n.id === otherNodeId);
          if (otherNode?.data.componentType === 'tool') {
            const toolConfig = otherNode.data.configuration as { toolId?: string; isCustom?: boolean; isKnowledgeBase?: boolean; lambdaCode?: string; inputSchema?: Record<string, unknown>; displayName?: string; description?: string } | undefined;
            if (toolConfig?.toolId === 'knowledge_base' && toolConfig?.isKnowledgeBase) {
              knowledgeBaseConfig = toolConfig as unknown as Record<string, unknown>;
            } else if (toolConfig?.toolId && !toolConfig?.isCustom) {
              gatewayTools.push(toolConfig.toolId);
            }
            if (toolConfig?.isCustom && toolConfig?.lambdaCode) {
              customTools.push({
                toolName: toolConfig.toolId || '',
                displayName: toolConfig.displayName || toolConfig.toolId || '',
                description: toolConfig.description || '',
                lambdaCode: toolConfig.lambdaCode,
                inputSchema: toolConfig.inputSchema || {},
              });
            }
          }
          // Detect Runtime nodes connected to gateway (MCP Server pattern).
          // Any non-deployable runtime connected to the gateway is treated as an MCP server target.
          if (otherNode?.data.componentType === 'runtime' && otherNode.data.configuration) {
            const runtimeCfg = otherNode.data.configuration as RuntimeConfiguration;
            const protocol = runtimeCfg.protocol || 'HTTP';
            // If this runtime has HTTP protocol, it's likely misconfigured — still treat it as MCP server
            // since it's connected to gateway and is not the deployable runtime.
            if (protocol === 'HTTP') {
              console.warn(`Runtime "${runtimeCfg.name}" connected to gateway has HTTP protocol — consider changing to MCP for MCP Server pattern.`);
            }
            mcpServerConfig = {
              name: runtimeCfg.name || 'mcp-server',
              framework: runtimeCfg.framework || 'strands_agents',
              systemPrompt: runtimeCfg.systemPrompt || '',
              model: runtimeCfg.model,
              tools: mcpServerTools, // will be populated from tool nodes connected to this runtime
            };
            // Find tool nodes connected to the MCP Server Runtime
            edges.forEach(mcpEdge => {
              if (mcpEdge.source === otherNodeId || mcpEdge.target === otherNodeId) {
                const mcpToolNodeId = mcpEdge.source === otherNodeId ? mcpEdge.target : mcpEdge.source;
                if (mcpToolNodeId === gatewayNodeId) return; // skip the gateway itself
                const mcpToolNode = nodes.find(n => n.id === mcpToolNodeId);
                if (mcpToolNode?.data.componentType === 'tool') {
                  const mcpToolCfg = mcpToolNode.data.configuration as { toolId?: string } | undefined;
                  if (mcpToolCfg?.toolId) {
                    mcpServerTools.push(mcpToolCfg.toolId);
                  }
                }
              }
            });
          }
        }
      });
    }

    return { tools: connectedTools, gatewayConfig, gatewayTools, identityConfig, customTools, memoryConfig, evaluationConfig, policyConfig, guardrailsConfig, mcpServerConfig, knowledgeBaseConfig };
  }, [deployableNodeId, edges, nodes]);

  const { tools: connectedTools, gatewayConfig, gatewayTools, identityConfig, customTools, memoryConfig, evaluationConfig, policyConfig, guardrailsConfig, mcpServerConfig, knowledgeBaseConfig } = getConnectedToolsAndGateway();

  // Handle pending node creation - open modal when node appears
  // Poll pending approvals for badge (15s interval)
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const s = await approvalStats();
        if (!cancelled) setPendingApprovalCount(s.pending);
      } catch {
        // unauthenticated or network — ignore
      }
    };
    void poll();
    const id = setInterval(poll, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (pendingNodeConfig) {
      const newNode = nodes.find((n) =>
        n.data.componentType === pendingNodeConfig.componentType &&
        Math.abs(n.position.x - pendingNodeConfig.position.x) < 20 &&
        Math.abs(n.position.y - pendingNodeConfig.position.y) < 20
      );

      if (newNode) {
        setConfigModal({
          isOpen: true,
          nodeId: newNode.id,
          componentType: pendingNodeConfig.componentType,
          initialConfig: newNode.data.configuration,
        });
        setPendingNodeConfig(null);
      }
    }
  }, [nodes, pendingNodeConfig]);

  const handleToggleCollapse = useCallback(() => {
    setPaletteCollapsed((prev) => !prev);
  }, []);

  const handleSearchChange = useCallback((query: string) => {
    setSearchQuery(query);
  }, []);

  // Open config modal for a node
  const handleOpenConfig = useCallback((nodeId: string) => {
    const node = nodes.find((n) => n.id === nodeId);
    if (node) {
      setConfigModal({
        isOpen: true,
        nodeId,
        componentType: node.data.componentType,
        initialConfig: node.data.configuration,
      });
    }
  }, [nodes]);

  // Handle node creation from drop - set pending to open modal when node appears
  // Tool nodes come pre-configured, so skip the modal for them
  const handleNodeCreate = useCallback((componentType: AgentCoreComponentType, position: { x: number; y: number }) => {
    if (componentType === 'tool') return;
    setPendingNodeConfig({ componentType, position });
  }, []);

  // Close config modal
  const handleCloseConfig = useCallback(() => {
    setConfigModal({ isOpen: false, nodeId: null, componentType: null });
  }, []);

  // Save configuration and run validation
  const handleSaveConfig = useCallback((config: ComponentConfiguration) => {
    if (configModal.nodeId) {
      updateNodeConfiguration(configModal.nodeId, config);
      // Run validation after config update
      setTimeout(() => runValidation(), 10);
    }
    handleCloseConfig();
  }, [configModal.nodeId, updateNodeConfiguration, runValidation, handleCloseConfig]);

  // Handle template selection
  const handleSelectTemplate = useCallback((template: WorkflowTemplate) => {
    const { nodes: templateNodes, edges: templateEdges } = instantiateTemplate(template);
    loadTemplate(templateNodes, templateEdges, template.id);
  }, [loadTemplate]);

  // Handle AI-generated tool → add as custom tool node on canvas
  const handleAddGeneratedTool = useCallback((tool: GeneratedTool) => {
    const toolConfig: ToolConfiguration = {
      name: tool.displayName,
      toolId: tool.toolName,
      description: tool.description,
      enabled: true,
      isCustom: true,
      lambdaCode: tool.lambdaCode,
      inputSchema: tool.inputSchema,
      displayName: tool.displayName,
    };

    // Place at a reasonable position on the canvas
    const existingToolNodes = nodes.filter(n => n.data.componentType === 'tool');
    const yOffset = existingToolNodes.length * 80;

    addNode({
      id: `tool-ai-${Date.now()}`,
      type: 'agentComponent',
      position: { x: 700, y: 150 + yOffset },
      data: {
        label: tool.displayName,
        componentType: 'tool',
        configuration: toolConfig,
        validationStatus: 'valid',
      },
    });

    setShowToolGenerator(false);
  }, [nodes, addNode]);

  // Check if we have a valid runtime to deploy
  const canDeploy = deployableConfig && deployableConfig.name && deployableConfig.systemPrompt;

  return (
    <div className="w-screen h-screen flex bg-[#f2f3f3]">
      <ComponentPalette
        collapsed={paletteCollapsed}
        onToggleCollapse={handleToggleCollapse}
        searchQuery={searchQuery}
        onSearchChange={handleSearchChange}
        onOpenTemplates={() => setShowTemplateGallery(true)}
        onOpenToolGenerator={() => setShowToolGenerator(true)}
      />

      <div className="flex-1 relative flex flex-col">
        {/* Top Header Bar */}
        <div className="h-12 bg-[#232f3e] flex items-center justify-between px-4 z-20">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-md bg-[#ff9900] flex items-center justify-center">
                <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                </svg>
              </div>
              <span className="font-semibold text-white text-sm tracking-tight">AgentCore Flows</span>
            </div>
            <div className="h-5 w-px bg-white/20" />
            <span className="font-medium text-white/80 text-sm">
              {activeFlowName || 'Untitled Flow'}
            </span>
            <div className="h-5 w-px bg-white/20" />
            <div className="flex items-center gap-2 text-xs text-white/60">
              <span className="px-2 py-0.5 bg-white/10 rounded font-medium">{nodes.length} node{nodes.length !== 1 ? 's' : ''}</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Status indicator */}
            {deployableConfig && (
              <div className="flex items-center gap-1.5 px-2.5 py-1 bg-emerald-500/15 text-emerald-400 rounded text-xs font-medium">
                <div className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
                Ready
              </div>
            )}

            {/* Deploy Button */}
            <button
              onClick={() => setShowDeployPanel(true)}
              disabled={!canDeploy}
              className={`
                px-4 py-1.5 rounded-md font-medium transition-all flex items-center gap-2 text-sm
                ${canDeploy
                  ? 'bg-[#ff9900] text-[#232f3e] hover:bg-[#ec7211] shadow-sm'
                  : 'bg-white/10 text-white/30 cursor-not-allowed'}
              `}
              title={!canDeploy ? 'Configure a Runtime node first' : 'Deploy to AgentCore'}
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4 20-7z" />
              </svg>
              Deploy
            </button>
            <button
              onClick={() => setShowHarnessManager(true)}
              className="px-3 py-1.5 rounded-md text-sm text-white/60 hover:text-white hover:bg-white/10 transition-colors"
              title="AgentCore Harness — managed agent"
            >
              Harness
            </button>
            <button
              onClick={() => setShowAgentCoreManager(true)}
              className="px-3 py-1.5 rounded-md text-sm text-white/60 hover:text-white hover:bg-white/10 transition-colors"
              title="AgentCore Optimization + Registry"
            >
              Services
            </button>
            <button
              onClick={() => setShowApprovalInbox(true)}
              className="relative px-3 py-1.5 rounded-md text-sm text-white/60 hover:text-white hover:bg-white/10 transition-colors"
              title="Approval Inbox"
            >
              Inbox
              {pendingApprovalCount > 0 && (
                <span
                  style={{
                    position: 'absolute',
                    top: -4,
                    right: -4,
                    background: '#ff9900',
                    color: '#232f3e',
                    fontSize: 10,
                    fontWeight: 700,
                    padding: '2px 6px',
                    borderRadius: 10,
                  }}
                >
                  {pendingApprovalCount}
                </span>
              )}
            </button>
            <button
              onClick={() => signOut()}
              className="px-3 py-1.5 rounded-md text-sm text-white/60 hover:text-white hover:bg-white/10 transition-colors"
              title="Sign out"
            >
              Sign out
            </button>
          </div>
        </div>

        {/* Canvas Area */}
        <div className="flex-1 relative">
          <WorkflowCanvas
            onNodeCreate={handleNodeCreate}
            onNodeDoubleClick={handleOpenConfig}
          />

          {/* Active Deployment Restore Banner */}
          <ActiveDeploymentBanner
            onRestore={handleRestoreDeployment}
          />

          {/* Selected Node Info Card */}
          {selectedNode && (
            <div className="absolute bottom-4 left-4 z-30 bg-white rounded-lg shadow-md border border-[#e9ebed] p-3.5 min-w-[220px]">
              <div className="flex items-start gap-2.5">
                <div className="w-9 h-9 rounded-md bg-[#232f3e] flex items-center justify-center text-white text-base flex-shrink-0">
                  {selectedNode.data.componentType === 'runtime' ? '🤖' :
                   selectedNode.data.componentType === 'gateway' ? '🔌' :
                   selectedNode.data.componentType === 'memory' ? '🧠' :
                   selectedNode.data.componentType === 'code_interpreter' ? '💻' :
                   selectedNode.data.componentType === 'browser' ? '🌐' :
                   selectedNode.data.componentType === 'observability' ? '📊' :
                   selectedNode.data.componentType === 'tool' ? '🔧' : '🔑'}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-[#16191f] text-sm truncate">
                    {selectedNode.data.label || selectedNode.data.componentType}
                  </div>
                  <div className="text-xs text-[#5f6b7a] capitalize mt-0.5">
                    {selectedNode.data.componentType.replace(/_/g, ' ')}
                  </div>
                </div>
              </div>
              <button
                onClick={() => handleOpenConfig(selectedNode.id)}
                className="mt-2.5 w-full py-1.5 px-3 text-sm text-[#0972d3] hover:bg-[#0972d3]/5 rounded-md transition-colors font-medium flex items-center justify-center gap-1.5 border border-[#0972d3]/20"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                Configure
              </button>
            </div>
          )}

          {/* Help hint when no nodes */}
          {nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="text-center max-w-xs">
                <div className="w-14 h-14 mx-auto mb-4 rounded-xl bg-[#232f3e] flex items-center justify-center">
                  <svg className="w-7 h-7 text-[#ff9900]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                  </svg>
                </div>
                <h3 className="text-base font-semibold text-[#16191f] mb-1">Build your workflow</h3>
                <p className="text-sm text-[#5f6b7a] mb-4">Drag components from the sidebar or start with a template</p>
                <button
                  onClick={() => setShowTemplateGallery(true)}
                  className="pointer-events-auto px-5 py-2 bg-[#0972d3] text-white rounded-md text-sm font-medium hover:bg-[#0961b9] transition-colors"
                >
                  Browse templates
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Deploy Panel */}
      <DeployPanel
        config={deployableConfig || null}
        nodeId={deployableNodeId}
        connectedTools={connectedTools}
        gatewayConfig={gatewayConfig}
        gatewayTools={gatewayTools}
        templateId={activeTemplateId}
        identityConfig={identityConfig}
        customTools={customTools}
        memoryConfig={memoryConfig}
        evaluationConfig={evaluationConfig}
        policyConfig={policyConfig}
        guardrailsConfig={guardrailsConfig}
        mcpServerConfig={mcpServerConfig}
        knowledgeBaseConfig={knowledgeBaseConfig}
        isVisible={showDeployPanel}
        onClose={() => setShowDeployPanel(false)}
        restoredDeployment={restoredDeployment}
      />

      {/* Configuration Modals */}
      {configModal.componentType === 'runtime' && (
        <RuntimeConfigurationModal
          isOpen={configModal.isOpen}
          onClose={handleCloseConfig}
          onSave={(config) => handleSaveConfig(config)}
          initialConfig={configModal.initialConfig as RuntimeConfiguration}
        />
      )}

      {configModal.componentType === 'gateway' && (
        <GatewayConfigurationModal
          isOpen={configModal.isOpen}
          onClose={handleCloseConfig}
          onSave={(config) => handleSaveConfig(config)}
          initialConfig={configModal.initialConfig as GatewayConfiguration}
        />
      )}

      {configModal.componentType === 'identity' && (
        <IdentityConfigurationModal
          isOpen={configModal.isOpen}
          onClose={handleCloseConfig}
          onSave={(config) => handleSaveConfig(config)}
          initialConfig={configModal.initialConfig as IdentityConfiguration}
        />
      )}

      {configModal.componentType === 'memory' && (
        <MemoryConfigurationModal
          isOpen={configModal.isOpen}
          onClose={handleCloseConfig}
          onSave={(config) => handleSaveConfig(config)}
          initialConfig={configModal.initialConfig as MemoryConfiguration}
        />
      )}

      {configModal.componentType === 'policy' && (
        <PolicyConfigurationModal
          isOpen={configModal.isOpen}
          onClose={handleCloseConfig}
          onSave={(config) => handleSaveConfig(config)}
          initialConfig={configModal.initialConfig as PolicyConfiguration}
        />
      )}

      {configModal.componentType === 'guardrails' && (
        <GuardrailsConfigurationModal
          isOpen={configModal.isOpen}
          onClose={handleCloseConfig}
          onSave={(config) => handleSaveConfig(config)}
          initialConfig={configModal.initialConfig as Partial<GuardrailsConfiguration>}
        />
      )}

      {configModal.componentType === 'tool' && !!(configModal.initialConfig as unknown as Record<string, unknown>)?.isKnowledgeBase && (
        <KnowledgeBaseConfigModal
          isOpen={configModal.isOpen}
          onClose={handleCloseConfig}
          onSave={(config) => handleSaveConfig(config)}
          initialConfig={configModal.initialConfig as Partial<KnowledgeBaseToolConfig>}
        />
      )}

      {/* Template Gallery Modal */}
      <TemplateGallery
        isOpen={showTemplateGallery}
        onClose={() => setShowTemplateGallery(false)}
        onSelectTemplate={handleSelectTemplate}
        hasExistingNodes={nodes.length > 0}
      />

      {/* AI Tool Generator Panel */}
      <ToolGeneratorPanel
        isVisible={showToolGenerator}
        onClose={() => setShowToolGenerator(false)}
        onAddToolToCanvas={handleAddGeneratedTool}
      />

      {/* Approval Inbox drawer (Task 02) */}
      <AnimatePresence>
        {showApprovalInbox && (
          <>
            <motion.div
              key="approval-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              onClick={() => setShowApprovalInbox(false)}
              className="fixed inset-0 bg-black/30 z-[999]"
              aria-hidden="true"
            />
            <motion.aside
              key="approval-drawer"
              role="dialog"
              aria-label="Approval inbox"
              aria-modal="true"
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'tween', ease: [0.32, 0.72, 0, 1], duration: 0.28 }}
              className="fixed top-0 right-0 h-screen w-full sm:w-[480px] max-w-full bg-white shadow-2xl border-l border-[#e9ebed] z-[1000] flex flex-col"
            >
              <ApprovalInbox onClose={() => setShowApprovalInbox(false)} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      {/* Harness Manager drawer (Task 11) */}
      <HarnessManager open={showHarnessManager} onClose={() => setShowHarnessManager(false)} />

      {/* AgentCore Services (Tasks 12 + 13) — Optimization + Registry */}
      <AgentCoreManager open={showAgentCoreManager} onClose={() => setShowAgentCoreManager(false)} />
    </div>
  );
}

export default App;
