import { Panel } from "@/components/panel";

export default function HomePage() {
  return (
    <div className="grid">
      <section className="hero">
        <div className="hero-card">
          <div className="badge">MVP Dashboard</div>
          <h1>Telegram 智能客服机器人</h1>
          <p className="muted">
            当前版本聚焦知识问答、风险分流、转人工和客服群接管。后台页面已按第一阶段需要铺好结构，后续可直接接真实 API。
          </p>
        </div>
      </section>

      <div className="grid grid-3">
        <Panel title="自动回复" description="规则优先、知识优先、模型最后。">
          <div className="stack">
            <div className="card">硬规则命中：人工/投诉/退款/敏感词</div>
            <div className="card">FAQ 优先，知识页次优，低置信度统一转人工</div>
          </div>
        </Panel>
        <Panel title="人工接管" description="客服群直接回客户。">
          <div className="stack">
            <div className="card">系统将摘要推送到内部 Telegram 客服群</div>
            <div className="card">群回复同步给客户，直到会话 release</div>
          </div>
        </Panel>
        <Panel title="平台扩展" description="单租户启动，模型与租户都预留扩展位。">
          <div className="stack">
            <div className="card">表结构保留 tenant_id / bot_profile_id</div>
            <div className="card">后续可继续加多租户、工具调用、知识导入</div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
