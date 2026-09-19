# MEPANANA EXTENSION - AI MASTER INSTRUCTIONS
> This project follows the official **MEPANANA MANIFESTO**: [docs/MEPANANA_MANIFESTO.md](file:///d:/OneDrive/@%20Elec.%20Hub/31_Tools%20&%20Addins/mepanana.extension/docs/MEPANANA_MANIFESTO.md)

## ⛔ CRITICAL MANDATE: NEVER MODIFY THE SECURITY SYSTEM
1. **DO NOT edit, refactor, or touch:**
   - \lib/py/auth.py\
   - \lib/py/MepananaAuth.dll\
   - \startup.py\
   - \hooks/app-init.py\
   - \hooks/doc-opened.py\
   - \hooks/view-activated.py\
2. **TOOL DEVELOPMENT STANDARD & PLAYBOOK:**
   - Always refer to [docs/MEPANANA_MANIFESTO.md](file:///d:/OneDrive/@%20Elec.%20Hub/31_Tools%20&%20Addins/mepanana.extension/docs/MEPANANA_MANIFESTO.md) and [docs/MEPANANA_DEVELOPER_PLAYBOOK.md](file:///d:/OneDrive/@%20Elec.%20Hub/31_Tools%20&%20Addins/mepanana.extension/docs/MEPANANA_DEVELOPER_PLAYBOOK.md) for UI/UX layouts, 6-line gatekeeper boilerplate, code architecture, and common pitfall checklists.

## ⚡ PYREVIT BUILT-IN FIRST PRINCIPLE (ZERO CODE REDUNDANCY)
1. **Always leverage pyRevit's built-in libraries first** (`pyrevit.forms`, `pyrevit.revit`, `pyrevit.DB`, `pyrevit.UI`, `pyrevit.script`, `pyrevit.framework`):
   - Whenever pyRevit already provides a built-in module, function, or helper (e.g. selection pickers, WPF windows `forms.WPFWindow`, dialogs, transaction managers, progress bars, settings storage, execution context), **DO NOT reinvent or create redundant custom code**.
   - Use pyRevit built-ins directly to simplify the codebase, minimize maintenance overhead, and guarantee native pyRevit performance.

## 🎨 MANDATORY ICON CREATION STANDARD (ROOT BENCHMARK: SCHEDULE LINK `SL`)
All pushbutton icons **MUST STRICTLY CONFORM** to the exact pixel metrics of `Schedule Link.pushbutton\icon.png`:
1. **Canvas**: $256 \times 256$ px, 32-bit ARGB PNG, 100% transparent background.
2. **Pushbutton Bounding Box (Exact Pixels)**:
   - **Height**: Strictly **$160\text{px}$** (Spanning $Y=50 \rightarrow Y=210$). Top Margin: $50\text{px}$, Bottom Margin: $46\text{px}$.
   - **Width**: **$160\text{px} - 235\text{px}$** (Centered, slim/condensed aspect ratio factor 0.80).
3. **Typography & Kerning**:
   - **Font**: `Segoe UI Bold` (`segoeuib.ttf`), Pushbutton: $220\text{pt}$, StackButton: $150\text{pt}$.
   - **Aspect Ratio**: Condensed / Slim horizontal ratio (0.80) for uniform, elegant strokes across all ribbon buttons.
   - **Character Spacing**: Natural positive gap $+8\text{px}$ (Pushbutton) / $+5\text{px}$ (StackButton).
4. **Color & Gradient (Horizontal Left-to-Right $X=0 \rightarrow X=255$)**:
   - Stop 0.00: `#15C27D` (Emerald Green)
   - Stop 0.18: `#20CB66` (Bright Green)
   - Stop 0.35: `#55C046` (Lime Green)
   - Stop 0.50: `#B4BC1E` (Yellow-Lime)
   - Stop 0.65: `#EBBF13` (Gold)
   - Stop 0.80: `#F48712` (Amber Orange)
   - Stop 1.00: `#F04A3C` (Fiery Red)
5. **Stacked Buttons (3-button Ribbon Stack)**:
   - Height: Strictly **$107\text{px}$** ($Y=74 \rightarrow Y=181$). Font: Size $150\text{pt}$, Slim factor $0.80$.
6. **Mandatory Generator Command**:
   - To generate a compliant icon, always run:
     `py lib/py/make_icon.py "<TEXT>" "<OUTPUT_PATH>"` (or `--stack` for stack buttons).

## 📊 MANDATORY PROGRESS BAR & DISPATCHER STANDARD
All tools with background or batch operations (CAD conversion, wiring, piping, clashing, Excel I/O, family downloads) **MUST STRICTLY CONFORM** to the unified Progress Bar standard:
1. **XAML Layout (Tier 3 FooterBar)**:
   - Place `<ProgressBar Name="progressBar" Grid.Row="0" Height="4" Margin="0,0,0,8" Visibility="Collapsed" IsIndeterminate="False" Minimum="0" Maximum="100"/>` spanning $100\%$ width across the top edge of the Footer (`Grid.Row="0"`).
   - Place `<TextBlock Name="txtStatus" .../>` on the left of `Grid.Row="1"` for live descriptive progress feedback.
2. **Execution & Message Pump**:
   - Always pump the WPF dispatcher queue using `from py.ui import do_events` during loop iterations to ensure immediate, non-blocking UI animation and prevent window freezing.
   - Standard 4-step lifecycle: Disable Run button & show ProgressBar (0%) -> Update progress & do_events() in loop -> Set 100% on complete -> Re-enable button & collapse ProgressBar in `finally` block.

## 🪟 MANDATORY WINDOW LIFECYCLE (MODELESS VS MODAL)
1. **Interactive Tools (Check Clash, Display Clash, Section Box, 3D Navigator)**:
   - **MUST USE** the True Modeless pattern: `win.Show()` + `Dispatcher.PushFrame(frame)` + `WindowInteropHelper.Owner`:
     ```python
     helper = WindowInteropHelper(win)
     helper.Owner = System.IntPtr(uidoc.Application.MainWindowHandle)
     frame = DispatcherFrame()
     win.Closed += lambda s, e: setattr(frame, 'Continue', False)
     win.Show()
     Dispatcher.PushFrame(frame)
     ```
   - **NEVER use bare `win.Show()` alone!** In IronPython, bare `Show()` exits script scope immediately, Garbage Collector cleans up the window while Revit holds Win32 pointers, causing an unrecoverable **FATAL ACCESS VIOLATION CRASH**.
2. **Short Configuration / Modal Tools (Shortcut Manager, Family Local)**:
   - Use standard modal `win.ShowDialog()`.
3. **Anti-Deadlock Object Picking**:
   - Always wrap `uidoc.Selection.PickObject()` or `PickElementsByRectangle()` in `with forms.HideWindow(self):` to prevent modal window mouse deadlocks.

## 🔤 MANDATORY TYPOGRAPHY STANDARD (STRICT ZERO BOLD RULE)
1. **Zero Bold / SemiBold in UI Body**:
   - All XAML TextBlocks, Labels, RadioButtons, CheckBoxes, and Badges **MUST USE** default `FontWeight="Normal"`.
   - **STRICTLY PROHIBITED:** `FontWeight="Bold"` or `FontWeight="SemiBold"` anywhere in XAML files (bolding is reserved exclusively for Theme SectionTitle styles).
2. **Theme DynamicResource Keys**:
   - Valid keys in `theme.xaml`: `CardStyle`, `CardBgBrush`, `WindowBgBrush`, `BorderBrush`, `SectionTitle`, `FieldLabel`, `PrimaryButton`, `GhostButton`, `AccentBrush`, `MutedTextBrush`, `TextBrush`.
   - **`TextBrush`** is `<SolidColorBrush x:Key="TextBrush" Color="#1E293B"/>`. You can safely reference `{DynamicResource TextBrush}` for primary text or use hardcoded `#0F172A` / `#1E293B`.

## 🎨 MANDATORY TRANSIENT VISUALIZATION STANDARD (AVF 3-COLOR)
1. **Transient Analysis Visualization Framework (AVF)**:
   - For all transient visual overlays (clash displays, highlight zones), **ALWAYS USE** Revit's native `SpatialFieldManager` (`Autodesk.Revit.DB.Analysis`).
   - **NEVER USE** `OverrideGraphicSettings` for clash visualization (it dirties model database, breaks View Templates, and cannot be cleanly undone).
2. **3-Tier Color Scheme**:
   - 🔴 **Red (`#EF4444` / `Color(239, 68, 68)`)**: Primary Host Model element.
   - 🟠 **Orange (`#F59E0B` / `Color(245, 158, 11)`)**: Secondary Host Model element (when 2 elements in the **SAME MODEL** clash).
   - 🟢 **Green (`#22C55E` / `Color(34, 197, 94)`)**: Linked Model element.
3. **Localized Element Footprint Geometry (Non-cluttering)**:
   - Extrude a localized footprint around the clash intersection point $(P_{clash} \pm \text{extent})$ with actual element width in **Counter-Clockwise (CCW)** vertex order for valid Revit extrusion solid faces.
   - Default extent is $\pm 600\text{ mm}$ ($\approx 1.2\text{ m}$ total segment length), clamped to element endpoints $[P_0, P_1]$.
   - This prevents plan-wide visual clutter across entire runs of pipes, ducts, cable trays, and walls.

## ⚙️ MANDATORY REVIT 2022+ API COMPATIBILITY CHECKLIST
1. **ElementId**: Always use `elem.Id.IntegerValue` (or `get_id_value()` in `core.py`). **NEVER** use `.Value` (Revit 2024+ only, crashes on Revit 2022).
2. **DWG / PDF Export**: Use `ExportPaperFormat.UseSheetSize` (Revit 2022). **NEVER** use `ExportPaperFormat.Default` (does not exist in Revit 2022).
3. **Collector Scoping**: Prefer view-scoped `FilteredElementCollector(doc, view.Id)` over document-scoped collectors. Always chain Quick Filters before Slow Filters.
4. **Transaction Integrity**: Group atomic operations into a single `SafeTransaction(doc, "Action")` for clean 1-step undo (Ctrl + Z).

## 🖱️ MANDATORY DYNAMIC XAML EVENT HANDLING (ZERO EVENT ATTRIBUTES IN XAML)
1. **Never Declare Event Attributes in `.xaml`**:
   - **STRICTLY PROHIBITED:** Declaring `Click="..."`, `Checked="..."`, `TextChanged="..."` directly inside `.xaml` files.
   - **Root Cause:** Dynamic XAML loaded via `XamlReader.Load()` (pyRevit's `forms.WPFWindow`) has no compiled `x:Class` code-behind. Any event attribute causes an immediate `XamlParseException` (`Failed to create a 'Click' from the text '...'`), crashing window initialization.
2. **Standard Event Wiring Pattern**:
   - **Standalone Controls**: Wire in Python `__init__`:
     `self.btnAction.Click += self.OnActionClick`
   - **Dynamic Card / ItemsControl Templates**: Attach routed event handlers to the parent container in Python `__init__`:
     ```python
     self.itemsControl.AddHandler(
         System.Windows.Controls.Button.ClickEvent,
         System.Windows.RoutedEventHandler(self.OnCardButtonClick)
     )
     self.itemsControl.AddHandler(
         System.Windows.Controls.CheckBox.ClickEvent,
         System.Windows.RoutedEventHandler(self.OnCardCheckboxClick)
     )
     ```
     Always set `IsHitTestVisible="False"` on inner TextBlock/StackPanel elements of template buttons so `args.Source` bubbles cleanly to the button.

## 📐 MANDATORY HIGH-DPI BUTTON & PRESET STANDARD
1. **Minimum Height $\ge 30\text{px}$**:
   - All standard buttons, preset filter pills, and card action buttons must have `Height >= 30` (standard: `Height="32"` or `Height="34"`).
   - In WPF with Segoe UI on Windows $125\% - 150\%$ High-DPI display scaling, buttons with `Height < 30` (e.g. 26px, 28px) or internal vertical padding will cause font baseline and descender clipping (`g`, `y`, `p`, `j`).
2. **Zero Vertical Padding & MinWidth**:
   - Always specify `MinWidth="0"` and zero vertical padding (e.g. `Padding="10,0"` or `Padding="0"`) on compact buttons and preset pills to ensure clean vertical centering.

## 🎯 MANDATORY INTERACTIVE PICKING & SILENT WORKFLOW STANDARD
1. **1-Click Direct Pick UX**:
   - Direct single-element tools (e.g. `Bloom`) should immediately trigger `PickObject()` when selection is empty, skipping modal configuration dialogs unless `Shift-Click` is detected.
2. **Continuous Loop Connection UX**:
   - Multi-element connection tools (e.g. `Connect To`) must run in a continuous interactive loop `while True:` wrapped in `try: ... except Autodesk.Revit.Exceptions.OperationCanceledException: break`, allowing users to connect multiple pairs seamlessly without re-launching the tool, exiting silently on `Esc`.
3. **Silent Success (No Popup Fatigue)**:
   - Do NOT show modal message dialogs or alerts upon successful completion. Let the visible model geometry changes provide immediate visual confirmation. Reserve popups only for critical unrecoverable errors.

## 🔌 MANDATORY MEP CONNECTOR & ROUTING TOLERANCE STANDARD
1. **Connector Pairing by Click Location (`ref.GlobalPoint`)**:
   - When the user clicks a linear element (pipe/duct/tray/conduit) to connect, always use `ref.GlobalPoint` to select the connector closest to where the user clicked, rather than an arbitrary index.
2. **Cable Tray vs. Conduit Disambiguation**:
   - Cable Trays and Conduits both share `DomainCableTrayConduit`. Always disambiguate target elements by checking element type/category (`isinstance(elem, CableTray)` vs `isinstance(elem, Conduit)`) before querying connectors or attempting fittings.
3. **Auto-Transition Fallback**:
   - When joining elements of differing widths/diameters/shapes, implement a 2-tier connection strategy: attempt direct fitting connection, and if sizes differ or direct connection fails, place `NewTransitionFitting` or match dimensions automatically before connecting.
4. **Collinear & Perpendicular Tolerances**:
   - Use normalized vector dot products with standard thresholds: parallel/collinear $|\vec{u} \cdot \vec{v}| \ge 0.999$, perpendicular $|\vec{u} \cdot \vec{v}| \le 0.001$.
   - For axial alignment, offset $\le 2\text{ mm}$ ($\approx 0.0065\text{ ft}$) is treated as collinear (Extend or Direct Join). Offset $\ge 5\text{ mm}$ triggers Bridge or Elbow routing to prevent zero-length curve exceptions.

## 🚀 MANDATORY CONTINUOUS GITHUB SYNC (ALWAYS PUSH TO GITHUB)
1. **Always Sync to GitHub**:
   - Whenever any task, feature implementation, bug fix, UI enhancement, or refactoring is completed and verified:
     **ALWAYS** stage, commit, and push changes to GitHub (`git add`, `git commit`, `git push origin <branch>`). Never leave working code uncommitted or unpushed at the end of a session or task.
2. **Pre-Push Verification Standard**:
   - Verify that 100% of Python files compile cleanly (`py -m compileall -q lib mepanana.tab`).
   - Verify that 0 security files are touched (`lib/py/auth.py`, `lib/py/MepananaAuth.dll`, `startup.py`, `hooks/`).
   - Verify that all `.xaml` files adhere strictly to the **Zero Bold Rule** and **Zero Inline Event Attributes Rule**.
3. **Commit Convention**:
   - Use clear, professional conventional commit messages (e.g. `feat: ...`, `fix: ...`, `refactor: ...`, `docs: ...`).