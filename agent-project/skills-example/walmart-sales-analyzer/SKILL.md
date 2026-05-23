---
name: walmart-sales-analyzer
description: 分析沃尔玛销售数据，探索门店销售额与失业率之间的趋势。生成富有洞察力的可视化和精美的 HTML 报告，附带深度分析。适用于快速了解销售数据与宏观经济指标之间的关系。
---

# 沃尔玛销售数据深度分析器

本技能旨在帮助用户对沃尔玛销售数据进行深度分析，特别是探索不同门店的销售额与失业率之间的关系。通过生成可视化图表并配以详细解读和专业 HTML 报告，直观地呈现这些趋势。

## 功能

本技能提供以下分析与可视化功能：

1.  **数据相关性热力图**：展示数据集中所有数值变量之间的相关关系，并提供详细解读。
2.  **销售额与失业率散点图**：直观展示周销售额与失业率之间的关系，配有回归线，深入分析经济压力下的消费韧性。
3.  **指定门店销售额与失业率的时间序列趋势**：追踪选定门店的销售额和失业率随时间的变化趋势，分析季节性因素与宏观趋势。
4.  **门店间平均销售额与平均失业率对比**：比较不同门店的平均销售业绩与当地平均失业率，为区域运营策略提供建议。
5.  **HTML 深度分析报告生成**：自动生成精美、响应式的 HTML 报告，整合所有图表，包含详细的分析结论和商业建议。

## 使用方法

使用本技能时，需要提供包含沃尔玛销售数据的 CSV 文件。该文件至少应包含以下列：`Store`（门店ID）、`Date`（日期）、`Weekly_Sales`（周销售额）、`Unemployment`（失业率）。

## 核心工作流

1. **检查上传文件**：首先验证是否提供了有效的沃尔玛销售 CSV 文件。
2. **执行分析脚本**：使用 `execute_skill_file` 工具运行 `generate_html_report.py` 脚本。将 CSV 文件路径传递给 `input_file` 参数。
   - 示例：`{"skill_name": "walmart-sales-analyzer", "script_file_name": "generate_html_report.py", "args": {"input_file": "/path/to/Walmart_Sales.csv", "output_dir": "."}}`
   - *注意：此脚本会自动生成所有所需的图表（`correlation_heatmap.png`、`sales_vs_unemployment_scatter.png` 等）和基础报告。*
3. **呈现报告**：通过 DB-GPT UI 向用户展示结果，必须使用 `html_interpreter` 工具。提供 `template_path`（`walmart-sales-analyzer/templates/report_template.html`）和必要的文本数据以交互式渲染报告。必须动态填充所有占位符（包括所有章节标题、报告标题和分析内容，否则将渲染为'NA'），并确保翻译为用户的语言。
   - 示例 `data` 负载：
     {
       "LANG": "zh",
       "REPORT_TITLE": "沃尔玛销售深度分析报告",
       "REPORT_SUBTITLE": "基于宏观经济指标与门店表现",
       "EXEC_SUMMARY_TITLE": "执行摘要",
       "EXEC_SUMMARY_CONTENT": "<p>您的详细摘要...</p>",
       "SECTION_1_TITLE": "1. 多维度相关性分析",
       "SECTION_1_ANALYSIS": "<h3><span class=\"tag\">洞察</span> 变量关系</h3><ul><li>...</li></ul>",
       "SECTION_2_TITLE": "2. 销售额与失业率回归分析",
       "SECTION_2_ANALYSIS": "<h3><span class=\"tag\">深度剖析</span> 压力下的韧性</h3><p>...</p>",
       "SECTION_3_TITLE": "3. 动态趋势追踪",
       "SECTION_3_ANALYSIS": "<h3><span class=\"tag\">趋势</span> 季节性 vs 宏观</h3><p>...</p>",
       "SECTION_4_TITLE": "4. 门店表现对比",
       "SECTION_4_ANALYSIS": "<h3><span class=\"tag\">策略</span> 区域运营</h3><p>...</p>",
       "CONCLUSION_TITLE": "最终结论与建议",
       "CONCLUSION_CONTENT": "<ol><li>...</li></ol>",
       "FOOTER_TEXT": "深度数据驱动决策"
     }
4. **完成任务**：调用 `terminate` 并附上总结操作结果的最终回答。

### 脚本列表

*   `scripts/generate_html_report.py`：**推荐**，一键生成包含所有图表和深度分析的 HTML 报告。
*   `scripts/generate_correlation_heatmap.py`：生成数据相关性热力图。
*   `scripts/generate_sales_unemployment_scatter.py`：生成销售额与失业率散点图。
*   `scripts/generate_time_series_trend.py`：生成指定门店的时间序列趋势图。
*   `scripts/generate_store_avg_comparison.py`：生成门店间平均值对比图。

### 模板

*   `templates/report_template.html`：用于生成深度分析报告的 HTML 样式模板。

## 重要提示

*   **语言要求：输出语言必须与用户输入/请求所使用的语言完全一致。**
*   所有图表均支持多语言显示。
*   报告模板采用响应式设计，适配不同设备查看，并提供详细的分析解读和商业建议。
