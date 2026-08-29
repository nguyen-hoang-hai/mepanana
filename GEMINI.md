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