"""
i18n module — translations for Bonsai 2 Control Panel (RU / EN / CN).

Usage:
    from i18n import t, set_language, current_language

    # Set language at startup or on change
    set_language("en")

    # Translate any key anywhere in the codebase
    label.setText(t("launch.model"))
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Translation tables
# Key format: "tab.section.item" — flat, dot-separated
# Default language is English; missing keys fall back to EN.
# ---------------------------------------------------------------------------

EN = {
    # --- Window / general ---
    "window.title": "Bonsai 2 Control Panel",
    "status.running": "Server running",
    "status.stopped": "Server stopped",
    "status.starting": "Starting server…",
    "status.stopping": "Stopping server…",

    # --- Tab names (toolbar) ---
    "tab.launch": "Launch",
    "tab.monitor": "Monitor",
    "tab.analytics": "Analytics",
    "tab.settings": "Settings",

    # --- Monitor tab — extra strings ---
    "monitor.process_metrics": "Process Metrics",
    "monitor.no_server": "\u26a0 Server not running. Go to Launch tab \u2192 Start Server.",
    "monitor.live_chart_title": "Live Resource Chart (from SQLite)",
    "monitor.logs_title": "Server Logs",
    "monitor.stderr_tab": "stderr (errors)",

    # --- Launch tab ---
    "launch.model": "Model",
    "launch.context_length": "Context Length",
    "launch.kv_cache": "KV Cache Type",
    "launch.mtp": "MTP Speculative Decoding",
    "launch.start_server": "Start Server",
    "launch.stop_server": "Stop Server",
    "launch.advanced_settings": "Advanced Settings",
    "launch.extra_args": "Extra CLI Args",
    "launch.rescan": "Rescan models",
    "launch.bonsai_8gb": "BONSAI_8GB=1 (8GB preset)",
    "launch.gpu_label": "{name} · VRAM {used}/{total} MiB · free {free} MiB",
    "launch.tkc_title": "Theoretical Speed (TKC)",
    "launch.tkc_value": "{tkc:.2f} tokens/s",
    "launch.model_not_found": "Model not found in models directory",
    "launch.start_error": "Failed to start server: {msg}",
    "launch.stop_error": "Failed to stop server: {msg}",
    # --- Launch tab — presets & custom values ---
    "launch.custom": "Custom",
    "launch.preset": "Preset:",
    "launch.save_preset": "Save Preset",
    "launch.preset_name": "Enter preset name",
    "launch.preset_recent": "Recent",

    # --- Launch tab — advanced settings ---
    "adv.spec_depth": "Spec Depth",
    "adv.ubatch": "UBatch",
    "adv.shared_pool": "Shared Pool",
    "adv.prefill_f16": "Prefill F16",
    "adv.fa_chunk": "FA Chunk",
    "adv.ckpt_every": "CKPT Every N",
    "adv.kv_vram_cells": "KV VRAM Cells",
    "adv.stage_cells": "Stage Cells",
    "adv.ram_budget_cache": "RAM Cache MiB",
    "adv.ram_budget_ckpts": "RAM CKPTs MiB",
    "adv.think": "Think",
    "adv.effort": "Effort",
    "adv.think_budget": "Think Budget",
    "adv.harness_proof": "Harness Proof",
    "adv.backend_sampling": "Backend Sampling",
    "adv.kq_mask_packed": "KQ Mask Packed",
    "adv.draft_window": "Draft Window",
    "adv.spec_deep": "Spec Deep",
    "adv.pool_mib": "Pool MiB",
    "adv.temp": "Temp",
    "adv.top_p": "Top-P",
    "adv.repeat_penalty": "Repeat Penalty",
    "adv.top_k": "Top-K",
    "adv.batch_size": "Batch Size",
    "adv.ngl": "NGL",
    "adv.lookup_n": "Lookup N (ngram)",
    "adv.reasoning_budget_message": "Reasoning Budget Message",
    "adv.reasoning_effort_fallback": "Reasoning Fallback Effort",

    # --- Advanced settings — groups ---
    "adv.group.spec_decoding": "Speculative Decoding",
    "adv.group.memory_kv": "Memory & KV Cache",
    "adv.group.sampling": "Sampling",
    "adv.group.batch_compute": "Batch & Compute",
    "adv.group.other": "Other",

    # --- Advanced settings tooltips ---
    "adv.tooltip.spec_depth": "Max draft tokens per speculative step. Higher = faster but more memory.",
    "adv.tooltip.draft_window": "Draft model context window in tokens. Controls history visible to the draft model.",
    "adv.tooltip.spec_deep": "Speculative depth multiplier: 1=small (fast), 4=large (accurate).",
    "adv.tooltip.backend_sampling": "Enable BONSAI_BS backend sampling for improved token generation quality.",
    "adv.tooltip.harness_proof": "Enable harness proof mode to verify speculative decoding results.",
    "adv.tooltip.kq_mask_packed": "Pack KQ attention mask into a single buffer for faster computation.",
    "adv.tooltip.think": "Enable extended thinking/reasoning before final response generation.",
    "adv.tooltip.think_budget": "Max tokens allocated for the thinking phase. 0 = unlimited.",
    "adv.tooltip.temp": "Sampling temperature: 0=greedy, 1=random. Higher = more diverse outputs.",
    "adv.tooltip.top_p": "Nucleus sampling threshold. Only sample from tokens with cumulative prob ≥ this value.",
    "adv.tooltip.repeat_penalty": "Penalty for repeated tokens. >1 discourages repetition.",
    "adv.tooltip.top_k": "Limit sampling to top K most probable tokens. 0 = disabled.",
    "adv.tooltip.batch_size": "Sequences processed in parallel per step. 0 = auto-detect.",
    "adv.tooltip.ubatch": "Micro-batch size for MTP speculative decoding. 0 = auto.",
    "adv.tooltip.prefill_f16": "Use FP16 for Flash Attention prefill. 0 = auto (default precision).",
    "adv.tooltip.fa_chunk": "Flash Attention chunk size in tokens. 0 = auto-detect optimal value.",
    "adv.tooltip.ckpt_every": "Save KV cache checkpoint every N tokens. 0 = disabled.",
    "adv.tooltip.ram_budget_cache": "Max RAM for KV cache in MiB. 0 = auto (use all available).",
    "adv.tooltip.ram_budget_ckpts": "Max RAM for checkpoints in MiB. 0 = auto (use all available).",
    "adv.tooltip.shared_pool": "Enable shared memory pool across GPU layers to reduce fragmentation.",
    "adv.tooltip.stage_cells": "KV cache cells per stage tier. Controls memory allocation granularity.",
    "adv.tooltip.kv_vram_cells": "Explicit KV cache cell count in VRAM. 0 = auto-detect from model size.",
    "adv.tooltip.pool_mib": "Shared pool size in MiB for GPU memory allocation. 0 = auto.",
    "adv.tooltip.ngl": "Number of layers offloaded to GPU (-ngl). Higher = faster but uses more VRAM.",
    "adv.tooltip.lookup_n": "Max n-gram length for speculative decoding lookup. Higher = more context per draft step, but slower search.",

    # --- Monitor tab ---
    "monitor.title": "Resource Monitor",
    "monitor.gpu": "GPU",
    "monitor.cpu": "CPU",
    "monitor.ram": "System RAM",
    "monitor.terminal": "Terminal Output",
    "monitor.refresh": "Refresh Interval: {n}s",

    # --- Analytics tab ---
    "analytics.title": "Data Analytics",
    "analytics.date_from": "From",
    "analytics.date_to": "To",
    "analytics.model_filter": "Model",
    "analytics.all_models": "(all models)",
    "analytics.kpi_requests": "Requests",
    "analytics.kpi_tokens": "Tokens",
    "analytics.kpi_cost": "Cost ($)",
    "analytics.kpi_avg": "Avg $/Req",
    # New KPIs (cache-aware)
    "analytics.kpi_cache_hit_1m": "1M INPUT (CACHE HIT)",
    "analytics.kpi_cache_miss_1m": "1M INPUT (CACHE MISS)",
    "analytics.kpi_output_1m": "1M OUTPUT TOKENS",
    "analytics.chart_title": "Requests & Tokens by Day",
    "analytics.deep_dive": "Deep Dive: {model}",
    "analytics.heatmap": "Heatmap: {model}",
    "analytics.no_data": "No data for selected range.",
    "analytics.no_cost_data": "No cost data — set Input/Output/Cached prices in Settings",
    "analytics.kpi_input": "Input (1M) $",
    "analytics.kpi_output": "Output (1M) $",
    "analytics.kpi_cached_input": "Cached Input (1M) $",
    "analytics.kpi_agent_cost": "Overall Cost ($)",
    "analytics.reload": "Reload",
    "analytics.data_table": "Data Table",
    # --- Chart axis labels ---
    "chart.y_cost": "Cost",
    "chart.y_hour": "Hour",

    # --- Settings tab ---
    "settings.title": "Settings",
    "settings.token_costs": "Token Costs (per 1M tokens, USD)",
    "settings.price_per_1m": "Price per 1M tokens ($)",
    "settings.price_input_1m": "Price / 1M input",
    "settings.price_output_1m": "Price / 1M output",
    "settings.price_cached_1m": "Price / 1M cached input",
    "settings.prompt_rate": "Prompt /1M",
    "settings.completion_rate": "Completion /1M",
    # --- Settings tab — theme ---
    "settings.theme": "Theme",
    "settings.color_scheme": "Color Scheme",
    "settings.paths": "Paths",
    "settings.data_path_label": "Data file path",
    "settings.api_key_label": "API key path",
    "settings.api_endpoint_label": "API endpoint",
    "settings.models_dir_label": "Models directory",
    "settings.llama_exe_label": "llama-server.exe path",
    "settings.browse_btn": "Browse…",
    "settings.ui_settings": "UI Settings",
    "settings.refresh_interval_label": "Refresh interval (s)",
    "settings.granularity_label": "Chart granularity",
    "settings.language": "Language",
    "settings.accent_color_label": "Accent color",
    "settings.pick_color_btn": "Pick Color",
    "settings.stats": "Statistics",
    "settings.stats_db_label": "Stats DB path",
    "settings.retention_label": "Retention (days)",
    "settings.sample_interval_label": "Sample interval (s)",
    "settings.lan_refresh": "Refresh LAN URLs",
    "settings.save": "Save Settings",
    "settings.saved": "Settings saved.",
    "settings.save_error": "Failed to save: {msg}",
    "settings.validation_error": "Validation errors:",

    # --- Performance mode ---
    "perf.mode_on": "Performance Mode ON (charts cleared, GC collected)",
    "perf.mode_off": "Performance Mode OFF",
    "perf.notify_title": "\u26a1 Performance Mode",
    "perf.notify_body": "GUI hidden. Server and stats are running. Ctrl+Shift+P or double-click the icon to return.",

    # --- Dialog buttons ---
    "dialog.ok": "OK",
    "dialog.cancel": "Cancel",
}

RU = {
    # --- Window / general ---
    "window.title": "Панель управления Bonsai 2",
    "status.running": "Сервер запущен",
    "status.stopped": "Сервер остановлен",
    "status.starting": "Запуск сервера…",
    "status.stopping": "Остановка сервера…",

    # --- Tab names (toolbar) ---
    "tab.launch": "Запуск",
    "tab.monitor": "Монитор",
    "tab.analytics": "Аналитика",
    "tab.settings": "Настройки",

    # --- Launch tab ---
    "launch.model": "Модель",
    "launch.context_length": "Длина контекста",
    "launch.kv_cache": "Тип KV кэша",
    "launch.mtp": "MTP спекулятивное декодирование",
    "launch.start_server": "Запустить сервер",
    "launch.stop_server": "Остановить сервер",
    "launch.advanced_settings": "Расширенные параметры",
    "launch.extra_args": "Доп. CLI аргументы",
    "launch.bonsai_8gb": "BONSAI_8GB=1 (пресет 8GB)",
    "launch.custom": "Своё значение",
    "launch.preset": "Пресет:",
    "launch.save_preset": "Сохранить пресет",
    "launch.preset_name": "Введите имя пресета",
    "launch.preset_recent": "Последний запуск",
    "launch.gpu_label": "{name} · VRAM {used}/{total} МБ · свободно {free} МБ",
    "launch.tkc_title": "Теоретическая скорость (TKC)",
    "launch.tkc_value": "{tkc:.2f} ток/с",
    "launch.model_not_found": "Модель не найдена в каталоге models",
    "launch.start_error": "Не удалось запустить сервер: {msg}",
    "launch.stop_error": "Не удалось остановить сервер: {msg}",
    "launch.rescan": "Пересканировать модели",

    # --- Launch tab — advanced settings ---
    "adv.spec_depth": "Spec Depth",
    "adv.ubatch": "UBatch",
    "adv.shared_pool": "Shared Pool",
    "adv.prefill_f16": "Prefill F16",
    "adv.fa_chunk": "FA Chunk",
    "adv.ckpt_every": "CKPT Every N",
    "adv.kv_vram_cells": "KV VRAM Cells",
    "adv.stage_cells": "Stage Cells",
    "adv.ram_budget_cache": "RAM Cache MiB",
    "adv.ram_budget_ckpts": "RAM CKPTs MiB",
    "adv.think": "Think",
    "adv.effort": "Effort",
    "adv.think_budget": "Think Budget",
    "adv.harness_proof": "Harness Proof",
    "adv.backend_sampling": "Backend Sampling",
    "adv.kq_mask_packed": "KQ Mask Packed",
    "adv.draft_window": "Draft Window",
    "adv.spec_deep": "Spec Deep",
    "adv.pool_mib": "Pool MiB",
    "adv.temp": "Temp",
    "adv.top_p": "Top-P",
    "adv.repeat_penalty": "Repeat Penalty",
    "adv.top_k": "Top-K",
    "adv.batch_size": "Batch Size",
    "adv.ngl": "NGL",
    "adv.lookup_n": "Lookup N (ngram)",
    "adv.reasoning_budget_message": "Сообщение reasoning budget",
    "adv.reasoning_effort_fallback": "Fallback Effort",

    # --- Advanced settings — группы ---
    "adv.group.spec_decoding": "Спекулятивное декодирование",
    "adv.group.memory_kv": "Память и KV Cache",
    "adv.group.sampling": "Сэмплирование",
    "adv.group.batch_compute": "Батч и вычисления",
    "adv.group.other": "Прочее",

    # --- Advanced settings tooltips (RU) ---
    "adv.tooltip.spec_depth": "Макс. число draft-токенов на шаг спекуляции. Выше = быстрее, но больше памяти.",
    "adv.tooltip.draft_window": "Окно контекста draft-модели в токенах. Определяет историю, видимую для draft.",
    "adv.tooltip.spec_deep": "Множитель глубины специ: 1=малая (быстро), 4=большая (точно).",
    "adv.tooltip.backend_sampling": "Включить BONSAI_BS backend sampling для улучшения генерации токенов.",
    "adv.tooltip.harness_proof": "Включить harness proof mode для верификации результатов спекулятивного декодирования.",
    "adv.tooltip.kq_mask_packed": "Упаковать KQ attention mask в один буфер для ускорения вычислений.",
    "adv.tooltip.think": "Включить расширенное рассуждение перед генерацией финального ответа.",
    "adv.tooltip.think_budget": "Макс. токенов для фазы think. 0 = без ограничений.",
    "adv.tooltip.temp": "Температура сэмплирования: 0=жадный, 1=случайный. Выше = более разнообразные выходы.",
    "adv.tooltip.top_p": "Порог ядра сэмплирования. Берём токены с кумулятивной вероятностью ≥ этого значения.",
    "adv.tooltip.repeat_penalty": "Штраф за повторяющиеся токены. >1 подавляет повторы.",
    "adv.tooltip.top_k": "Ограничить выборку top K наиболее вероятных токенов. 0 = выкл.",
    "adv.tooltip.batch_size": "Число последовательностей параллельно на шаг. 0 = авто.",
    "adv.tooltip.ubatch": "Размер микро-батча для MTP спекулятивного декодирования. 0 = авто.",
    "adv.tooltip.prefill_f16": "Использовать FP16 для Flash Attention prefill. 0 = авто (стандартная точность).",
    "adv.tooltip.fa_chunk": "Размер chunk Flash Attention в токенах. 0 = автооптимальное значение.",
    "adv.tooltip.ckpt_every": "Сохранять checkpoint KV cache каждые N токенов. 0 = выкл.",
    "adv.tooltip.ram_budget_cache": "Макс. RAM для KV cache, МБ. 0 = авто (все доступные).",
    "adv.tooltip.ram_budget_ckpts": "Макс. RAM для checkpoints, МБ. 0 = авто (все доступные).",
    "adv.tooltip.shared_pool": "Включить общий пул памяти между GPU слоями для снижения фрагментации.",
    "adv.tooltip.stage_cells": "Ячейки KV cache на stage tier. Определяет гранулярность выделения памяти.",
    "adv.tooltip.kv_vram_cells": "Явное число ячеек KV cache в VRAM. 0 = авто по размеру модели.",
    "adv.tooltip.pool_mib": "Размер shared pool, МБ для GPU memory allocation. 0 = авто.",
    "adv.tooltip.ngl": "Число слоёв на GPU (-ngl). Выше = быстрее, но больше VRAM.",

    # --- Monitor tab ---
    "monitor.title": "Монитор ресурсов",
    "monitor.process_metrics": "Метрики процесса",
    "monitor.no_server": "\u26a0 Сервер не запущен. Tab 1 \u2192 «Start Server».",
    "monitor.live_chart_title": "Live-график ресурсов (из SQLite)",
    "monitor.logs_title": "Логи сервера",
    "monitor.stderr_tab": "stderr (ошибки)",
    "monitor.gpu": "GPU",

    "monitor.cpu": "CPU",
    "monitor.ram": "Системная RAM",
    "monitor.terminal": "Вывод терминала",
    "monitor.refresh": "Интервал обновления: {n}с",

    # --- Analytics tab ---
    "analytics.title": "Аналитика данных",
    "analytics.date_from": "С даты",
    "analytics.date_to": "По дату",
    "analytics.model_filter": "Модель",
    "analytics.all_models": "(все модели)",
    "analytics.kpi_requests": "Запросы",
    "analytics.kpi_tokens": "Токены",
    "analytics.kpi_cost": "Стоимость ($)",
    "analytics.kpi_avg": "Сред. $/запрос",
    # New KPIs (cache-aware)
    "analytics.kpi_cache_hit_1m": "1M INPUT (CACHE HIT)",
    "analytics.kpi_cache_miss_1m": "1M INPUT (CACHE MISS)",
    "analytics.kpi_output_1m": "1M OUTPUT TOKENS",
    "analytics.chart_title": "Запросы и токены по дням",
    "analytics.deep_dive": "Подробный анализ: {model}",
    "analytics.heatmap": "Тепловая карта: {model}",
    # --- Подписи осей графиков ---
    "chart.y_cost": "Стоимость",
    "chart.y_hour": "Час",
    "analytics.no_data": "Нет данных для выбранного периода.",
    "analytics.no_cost_data": "Нет данных о стоимости — задайте цены Input/Output/Cached в Настройках",
    "analytics.kpi_input": "Input (1M) $",
    "analytics.kpi_output": "Output (1M) $",
    "analytics.kpi_cached_input": "Cached Input (1M) $",
    "analytics.kpi_agent_cost": "Общая стоимость ($)",
    "analytics.reload": "Обновить",
    "analytics.data_table": "Таблица данных",

    # --- Settings tab ---
    "settings.title": "Настройки",
    "settings.token_costs": "Стоимость токенов (за 1M, USD)",
    "settings.price_per_1m": "Цена за 1M токенов ($)",
    "settings.price_input_1m": "Цена ввода за 1M токенов",
    "settings.price_output_1m": "Цена вывода за 1M токенов",
    "settings.price_cached_1m": "Цена кэша за 1M токенов",
    "settings.prompt_rate": "Prompt /1M",
    "settings.completion_rate": "Completion /1M",
    # --- Settings tab — theme ---
    "settings.theme": "Тема",
    "settings.color_scheme": "Цветовая схема",
    "settings.paths": "Пути",
    "settings.data_path_label": "Путь к файлу данных",
    "settings.api_key_label": "Путь к API ключу",
    "settings.api_endpoint_label": "API endpoint",
    "settings.models_dir_label": "Каталог моделей",
    "settings.llama_exe_label": "Путь к llama-server.exe",
    "settings.browse_btn": "Обзор…",
    "settings.ui_settings": "Настройки UI",
    "settings.refresh_interval_label": "Интервал обновления (с)",
    "settings.granularity_label": "Гранулярность графиков",
    "settings.language": "Язык",
    "settings.accent_color_label": "Акцентный цвет",
    "settings.pick_color_btn": "Выбрать цвет",
    "settings.stats": "Статистика",
    "settings.stats_db_label": "Путь к Stats DB",
    "settings.retention_label": "Срок хранения (дней)",
    "settings.sample_interval_label": "Интервал сэмплирования (с)",
    "settings.lan_refresh": "Обновить LAN URL",
    "settings.save": "Сохранить настройки",
    "settings.saved": "Настройки сохранены.",
    "settings.save_error": "Не удалось сохранить: {msg}",
    "settings.validation_error": "Ошибки валидации:",

    # --- Performance mode ---
    "perf.mode_on": "Режим производительности ВКЛ (графики очищены, GC собран)",
    "perf.mode_off": "Режим производительности ВЫКЛ",
    "perf.notify_title": "\u26a1 Режим производительности",
    "perf.notify_body": "GUI скрыт. Сервер и статистика работают. Ctrl+Shift+P или двойной клик по иконке — вернуться.",

    # --- Dialog buttons ---
    "dialog.ok": "ОК",
    "dialog.cancel": "Отмена",
}

CN = {
    # --- Window / general ---
    "window.title": "Bonsai 2 控制面板",
    "status.running": "服务器运行中",
    "status.stopped": "服务器已停止",
    "status.starting": "正在启动服务器…",
    "status.stopping": "正在停止服务器…",

    # --- Tab names (toolbar) ---
    "tab.launch": "启动",
    "tab.monitor": "监控",
    "tab.analytics": "分析",
    "tab.settings": "设置",

    # --- Launch tab ---
    "launch.model": "模型",
    "launch.context_length": "上下文长度",
    "launch.kv_cache": "KV 缓存类型",
    "launch.mtp": "MTP 投机解码",
    "launch.start_server": "启动服务器",
    "launch.stop_server": "停止服务器",
    "launch.advanced_settings": "高级设置",
    "launch.extra_args": "额外 CLI 参数",
    "launch.rescan": "重新扫描模型",
    "launch.bonsai_8gb": "BONSAI_8GB=1 (8GB 预设)",
    "launch.custom": "自定义值",
    "launch.preset": "预设:",
    "launch.save_preset": "保存预设",
    "launch.preset_name": "请输入预设名称",
    "launch.preset_recent": "最近一次启动",
    "launch.gpu_label": "{name} · VRAM {used}/{total} MiB · 空闲 {free} MiB",
    "launch.tkc_title": "理论速度 (TKC)",
    "launch.tkc_value": "{tkc:.2f} tok/s",
    "launch.model_not_found": "在 models 目录中未找到模型",
    "launch.start_error": "启动服务器失败: {msg}",
    "launch.stop_error": "停止服务器失败: {msg}",

    # --- Launch tab — advanced settings ---
    "adv.spec_depth": "Speculative Depth",
    "adv.ubatch": "Micro-Batch (UBatch)",
    "adv.shared_pool": "Shared Memory Pool",
    "adv.prefill_f16": "Prefill F16",
    "adv.fa_chunk": "FA Chunk Size",
    "adv.ckpt_every": "CKPT Every N Tokens",
    "adv.kv_vram_cells": "KV VRAM Cells",
    "adv.stage_cells": "Stage Cells",
    "adv.ram_budget_cache": "RAM Cache (MiB)",
    "adv.ram_budget_ckpts": "RAM CKPTs (MiB)",
    "adv.think": "Extended Thinking",
    "adv.effort": "Reasoning Effort",
    "adv.think_budget": "Think Budget (tokens)",
    "adv.harness_proof": "Harness Proof Mode",
    "adv.backend_sampling": "Backend Sampling",
    "adv.kq_mask_packed": "KQ Mask Packed",
    "adv.draft_window": "Draft Window (tokens)",
    "adv.spec_deep": "Speculative Depth Multiplier",
    "adv.pool_mib": "Shared Pool Size (MiB)",
    "adv.temp": "Temperature",
    "adv.top_p": "Top-P",
    "adv.repeat_penalty": "Repeat Penalty",
    "adv.top_k": "Top-K",
    "adv.batch_size": "Batch Size",
    "adv.ngl": "GPU Layers (NGL)",
    "adv.lookup_n": "Lookup N (ngram)",
    "adv.reasoning_budget_message": "Reasoning Budget Message",
    "adv.reasoning_effort_fallback": "Fallback Effort",

    # --- Advanced settings — groups (CN) ---
    "adv.group.spec_decoding": "投机解码",
    "adv.group.memory_kv": "内存与 KV Cache",
    "adv.group.sampling": "采样",
    "adv.group.batch_compute": "批处理与计算",
    "adv.group.other": "其他",

    # --- Monitor tab ---
    "monitor.title": "资源监控",
    "monitor.process_metrics": "进程指标",
    "monitor.no_server": "\u26a0 服务器未运行。前往启动标签 \u2192 启动服务器。",
    "monitor.live_chart_title": "实时资源图表（来自 SQLite）",
    "monitor.logs_title": "服务器日志",
    "monitor.stderr_tab": "stderr (错误)",
    "monitor.gpu": "GPU",

    "monitor.cpu": "CPU",
    "monitor.ram": "系统 RAM",
    "monitor.terminal": "终端输出",
    "monitor.refresh": "刷新间隔: {n}s",

    # --- Analytics tab ---
    "analytics.title": "数据分析",
    "analytics.date_from": "起始日期",
    "analytics.date_to": "结束日期",
    "analytics.model_filter": "模型",
    "analytics.all_models": "(所有模型)",
    "analytics.kpi_requests": "请求数",
    "analytics.kpi_tokens": "Token 数",
    "analytics.kpi_cost": "成本 ($)",
    "analytics.kpi_avg": "平均 $/请求",
    # New KPIs (cache-aware)
    "analytics.kpi_cache_hit_1m": "1M INPUT (CACHE HIT)",
    "analytics.kpi_cache_miss_1m": "1M INPUT (CACHE MISS)",
    "analytics.kpi_output_1m": "1M OUTPUT TOKENS",
    # --- 图表轴标签 ---
    "chart.y_cost": "成本",
    "chart.y_hour": "小时",
    "analytics.chart_title": "每日请求与 Token 数",
    "analytics.deep_dive": "详细分析: {model}",
    "analytics.heatmap": "热力图: {model}",
    "analytics.no_data": "所选范围内无数据。",
    "analytics.no_cost_data": "无成本数据 — 请在设置中配置 Input/Output/Cached 价格",
    "analytics.kpi_input": "Input (1M) $",
    "analytics.kpi_output": "Output (1M) $",
    "analytics.kpi_cached_input": "Cached Input (1M) $",
    "analytics.kpi_agent_cost": "总成本 ($)",
    "analytics.reload": "重新加载",
    "analytics.data_table": "数据表",

    # --- Settings tab ---
    "settings.title": "设置",
    "settings.token_costs": "Token 成本 (每 1M, USD)",
    "settings.price_per_1m": "每 1M token 价格 ($)",
    "settings.price_input_1m": "输入每 1M token 价格",
    "settings.price_output_1m": "输出每 1M token 价格",
    "settings.price_cached_1m": "缓存每 1M token 价格",
    "settings.prompt_rate": "Prompt /1M",
    "settings.completion_rate": "Completion /1M",
    # --- Settings tab — theme ---
    "settings.theme": "主题",
    "settings.color_scheme": "配色方案",
    "settings.paths": "路径",
    "settings.data_path_label": "数据文件路径",
    "settings.api_key_label": "API 密钥路径",
    "settings.api_endpoint_label": "API endpoint",
    "settings.models_dir_label": "模型目录",
    "settings.llama_exe_label": "llama-server.exe 路径",
    "settings.browse_btn": "浏览…",
    "settings.ui_settings": "UI 设置",
    "settings.refresh_interval_label": "刷新间隔 (秒)",
    "settings.granularity_label": "图表粒度",
    "settings.language": "语言",
    "settings.accent_color_label": "强调色",
    "settings.pick_color_btn": "选择颜色",
    "settings.stats": "统计",
    "settings.stats_db_label": "Stats DB 路径",
    "settings.retention_label": "保留天数",
    "settings.sample_interval_label": "采样间隔 (秒)",
    "settings.lan_refresh": "刷新 LAN URL",
    "settings.save": "保存设置",
    "settings.saved": "设置已保存。",
    "settings.save_error": "保存失败: {msg}",
    "settings.validation_error": "验证错误:",

    # --- Performance mode ---
    "perf.mode_on": "性能模式开启 (图表已清除, GC 已收集)",
    "perf.mode_off": "性能模式关闭",
    "perf.notify_title": "\u26a1 性能模式",
    "perf.notify_body": "GUI 已隐藏。服务器和统计正在运行。Ctrl+Shift+P 或双击图标返回。",

    # --- Dialog buttons ---
    "dialog.ok": "确定",
    "dialog.cancel": "取消",
}


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------
_TRANSLATIONS = {"en": EN, "ru": RU, "cn": CN}
_DEFAULT_LANG = "en"
_current_lang: str = _DEFAULT_LANG


def set_language(lang: str) -> None:
    """Set the active language. Unknown values fall back to English."""
    global _current_lang
    if lang in _TRANSLATIONS:
        _current_lang = lang
    else:
        _current_lang = _DEFAULT_LANG


def current_language() -> str:
    """Return the currently active language code."""
    return _current_lang


def t(key: str, **kwargs) -> str:
    """
    Translate a key to the current language.

    - Looks up `key` in the active language table.
    - Falls back to English if the key is missing in the active language.
    - Supports `{placeholder}` formatting via **kwargs.
    - Returns the raw key if no translation exists anywhere (safe for dev).
    """
    tables = [_TRANSLATIONS.get(_current_lang, EN), EN]
    for table in tables:
        if key in table:
            text = table[key]
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError):
                # If a placeholder is missing, return the raw string
                return text
    return key
