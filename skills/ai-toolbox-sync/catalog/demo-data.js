// Generated from the audited manifest; do not edit.
window.TOOLBOX_DEMO = {
  "exampleOnly": true,
  "resources": [
    {
      "id": "skill:self:sample-notes",
      "name": "sample-notes",
      "description": "整理自己的笔记工作流。",
      "version": "unknown",
      "resolvedCommit": "unknown",
      "license": "owner-defined",
      "ownership": "self",
      "management": "managed",
      "verification": "unknown",
      "categories": [
        "知识管理"
      ],
      "summary": "将零散笔记整理为结构清晰的主题摘要，便于后续查阅。",
      "triggerPrompt": "请使用 $sample-notes，将以下笔记整理为主题摘要：[粘贴笔记]。",
      "state": {
        "decision": "approved",
        "collection": "collected",
        "installation": "unknown",
        "sync": "failed",
        "catalog": "current"
      },
      "kind": "skill",
      "projectUrl": null
    },
    {
      "id": "mcp:third-party:example-docs",
      "name": "example-docs",
      "description": "连接文档服务的示例配置。",
      "version": "unknown",
      "resolvedCommit": "unknown",
      "license": "unknown",
      "ownership": "third-party",
      "management": "approved",
      "verification": "configured-only",
      "categories": [
        "文档检索"
      ],
      "summary": "演示连接文档服务并记录可迁移配置；真实检索能力尚未验证。",
      "triggerPrompt": "",
      "state": {
        "decision": "approved",
        "collection": "not-collected",
        "installation": "configured",
        "sync": "not-requested",
        "catalog": "current"
      },
      "kind": "mcp",
      "projectUrl": "https://example.invalid/project"
    },
    {
      "id": "plugin:third-party:example-market/example-plugin",
      "name": "example-plugin",
      "description": "记录插件的来源与固定版本。",
      "version": "unknown",
      "resolvedCommit": "unknown",
      "license": "unknown",
      "ownership": "third-party",
      "management": "pending",
      "verification": "unknown",
      "categories": [
        "工具管理"
      ],
      "summary": "演示记录插件来源、版本与纳管信息；不代表已安装插件。",
      "triggerPrompt": "",
      "state": {
        "decision": "pending",
        "collection": "not-collected",
        "installation": "unknown",
        "sync": "not-requested",
        "catalog": "current"
      },
      "kind": "plugin",
      "projectUrl": "https://example.invalid/plugin"
    },
    {
      "id": "skill:self:sample-image",
      "name": "sample-image",
      "description": "根据产品资料与视觉要求生成图片，并检查与需求的一致性。",
      "version": "unknown",
      "resolvedCommit": "unknown",
      "license": "unknown",
      "ownership": "self",
      "management": "pending",
      "verification": "unknown",
      "categories": [
        "生图"
      ],
      "summary": "根据产品资料与视觉要求生成图片，并检查与需求的一致性。",
      "triggerPrompt": "请使用 $sample-image，根据[产品资料]生成[用途]图片，要求：[比例、风格与限制]。",
      "state": {
        "decision": "pending",
        "collection": "not-collected",
        "installation": "unknown",
        "sync": "not-requested",
        "catalog": "current"
      },
      "kind": "skill",
      "projectUrl": null
    },
    {
      "id": "skill:self:sample-design",
      "name": "sample-design",
      "description": "设计网页界面的布局、视觉层级与响应式交互。",
      "version": "unknown",
      "resolvedCommit": "unknown",
      "license": "unknown",
      "ownership": "self",
      "management": "pending",
      "verification": "unknown",
      "categories": [
        "设计"
      ],
      "summary": "设计网页界面的布局、视觉层级与响应式交互。",
      "triggerPrompt": "请使用 $sample-design，为[页面用途]设计界面，包含[主要内容与交互要求]。",
      "state": {
        "decision": "pending",
        "collection": "not-collected",
        "installation": "unknown",
        "sync": "not-requested",
        "catalog": "current"
      },
      "kind": "skill",
      "projectUrl": null
    },
    {
      "id": "skill:self:sample-code",
      "name": "sample-code",
      "description": "定位代码问题、实施必要修复并运行针对性测试。",
      "version": "unknown",
      "resolvedCommit": "unknown",
      "license": "unknown",
      "ownership": "self",
      "management": "pending",
      "verification": "unknown",
      "categories": [
        "编程"
      ],
      "summary": "定位代码问题、实施必要修复并运行针对性测试。",
      "triggerPrompt": "请使用 $sample-code，检查[项目或文件]中的[问题现象]，完成修复并验证。",
      "state": {
        "decision": "pending",
        "collection": "not-collected",
        "installation": "unknown",
        "sync": "not-requested",
        "catalog": "current"
      },
      "kind": "skill",
      "projectUrl": null
    }
  ]
};
