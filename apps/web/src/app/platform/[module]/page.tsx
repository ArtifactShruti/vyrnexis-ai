import Link from "next/link";
import AgentsWorkspace from "@/components/AgentsWorkspace";
import EvidenceVault from "@/components/EvidenceVault";
import AssetInventory from "@/components/AssetInventory";
import SecurityOperations from "@/components/SecurityOperations";
import DataSourcesWorkspace from "@/components/DataSourcesWorkspace";
import FraudWorkspace from "@/components/FraudWorkspace";
import ForensicsWorkspace from "@/components/ForensicsWorkspace";
import NexusWorkspace from "@/components/NexusWorkspace";
import AiSettingsWorkspace from "@/components/AiSettingsWorkspace";
import KnowledgeWorkspace from "@/components/KnowledgeWorkspace";
import CopilotWorkspace from "@/components/CopilotWorkspace";
import WorkflowWorkspace from "@/components/WorkflowWorkspace";
import DigitalTwinWorkspace from "@/components/DigitalTwinWorkspace";
import BusinessIntelligenceWorkspace from "@/components/BusinessIntelligenceWorkspace";
import PremiumModuleWorkspace from "@/components/PremiumModuleWorkspace";
import OrganizationWorkspace from "@/components/OrganizationWorkspace";
import ThreatWorkspace from "@/components/ThreatWorkspace";
import EcommerceWorkspace from "@/components/EcommerceWorkspace";
import ReportsWorkspace from "@/components/ReportsWorkspace";
import DeveloperPortal from "@/components/DeveloperPortal";
import ObservabilityWorkspace from "@/components/ObservabilityWorkspace";
import HelpCenter from "@/components/HelpCenter";
import NotificationsWorkspace from "@/components/NotificationsWorkspace";

const titles: Record<string,string> = {
  security: "Security Operations",
  forensics: "Digital Forensics Laboratory",
  fraud: "Fraud Intelligence",
  analytics: "Business Intelligence",
  "digital-twin": "Digital Twin Simulator",
  workflows: "Workflow Automation",
  agents: "AI Agent Management",
  assets: "Asset Inventory",
  "system-health": "System Health",
  "help": "Documentation and Help",
  "threats": "Threat Intelligence",
  "ecommerce": "E-commerce Analytics",
  "reports": "Reports Center",
  "developer": "Developer API Portal",
  "integrations": "Integration Marketplace",
  "notifications": "Notification Center",
  "users": "User Management",
  "billing": "Subscription and Billing",
  "super-admin": "Super Administrator",
  "onboarding": "Organization Onboarding",
  "settings": "Organization Settings",
  "roles": "Role and Permission Management",
  "audit": "Audit Logs"
};

export default async function ModulePage({ params }: { params: Promise<{module:string}> }) {
  const { module } = await params;
  const title = titles[module] || "Platform Workspace";

  if (module === "agents") return <AgentsWorkspace />;
  if (module === "forensics") return <ForensicsWorkspace />;
  if (module === "evidence-vault") return <EvidenceVault />;
  if (module === "nexus") return <NexusWorkspace />;
  if (module === "ai-settings") return <AiSettingsWorkspace />;
  if (module === "knowledge") return <KnowledgeWorkspace />;
  if (module === "copilot") return <CopilotWorkspace />;
  if (module === "workflows") return <WorkflowWorkspace />;
  if (module === "digital-twin") return <DigitalTwinWorkspace />;
  if (module === "analytics") return <BusinessIntelligenceWorkspace />;
  if (module === "assets") return <AssetInventory />;
  if (module === "security") return <SecurityOperations />;
  if (module === "data-sources") return <DataSourcesWorkspace />;
  if (module === "fraud") return <FraudWorkspace />;
  if (module === "threats") return <ThreatWorkspace />;
  if (module === "ecommerce") return <EcommerceWorkspace />;
  if (module === "reports") return <ReportsWorkspace />;
  if (module === "developer") return <DeveloperPortal />;
  if (module === "system-health") return <ObservabilityWorkspace />;
  if (module === "help") return <HelpCenter />;
  if (module === "notifications") return <NotificationsWorkspace />;
  if (module === "integrations") return <PremiumModuleWorkspace module="integrations" title="Integration marketplace" description="Authorized data-source integrations and live ingestion configuration." />;
  if (module === "notifications") return <PremiumModuleWorkspace module="notifications" title="Notification center" description="Recent organization activity derived from immutable audit records." />;
  if (module === "users") return <PremiumModuleWorkspace module="users" title="User management" description="Create and manage organization users with server-enforced roles." />;
  if (module === "billing") return <PremiumModuleWorkspace module="billing" title="Subscription and billing" description="Account and AI usage status. No subscription provider or charge data is fabricated." />;
  if (module === "super-admin") return <PremiumModuleWorkspace module="super-admin" title="Super administrator" description="Organization-scoped platform status with tenant isolation preserved." />;
  if (module === "onboarding") return <OrganizationWorkspace onboarding />;
  if (module === "settings") return <OrganizationWorkspace />;
  if (module === "roles") return <PremiumModuleWorkspace module="roles" title="Role and permission management" description="Role inventory and organization user assignment; effective permissions are enforced by the API." />;
  if (module === "audit") return <PremiumModuleWorkspace module="audit" title="Audit logs" description="Tenant-scoped immutable administrative and domain activity." />;

  return (
    <main style={{minHeight:"100vh",padding:"28px"}}>
      <div style={{maxWidth:1100,margin:"0 auto"}}>
        <Link className="button" href="/">← Command Center</Link>
        <h1 style={{marginTop:24}}>{title}</h1>
        <div className="card panel" style={{marginTop:16}}>
          <div className="panel-head"><h2>{title} workspace</h2><span>API-backed module</span></div>
          <p style={{color:"#94a3b8",lineHeight:1.7}}>
            This workspace is connected to the Vyrnexis API. Live records appear only after an organization is registered or configured.
            No synthetic metrics or fabricated integration state are displayed.
          </p>
          <a className="button primary" href="/api/dashboard">Check live dashboard API</a>
        </div>
      </div>
    </main>
  );
}
