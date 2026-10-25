---
name: Honeycomb Abaqus Studio
description: Native Windows workbench for reproducible configuration, execution and evidence tracing.
typography:
  provenance:
    fontSize: "12px"
  resource-summary:
    fontSize: "15px"
  diagnostic:
    fontFamily: "Consolas"
spacing:
  compact: "8px"
  related: "12px"
  group: "16px"
  workspace: "24px"
---

# Design System: Honeycomb Abaqus Studio

## Overview

**Creative North Star: "The Reproducible Research Workbench"**

A dense, restrained engineering workspace built with native WinUI 3 Fluent controls and Windows system typography. The visual story follows study configuration, batch and run control, then inspectable evidence and datasets. Units, provenance and attempt identity carry more weight than decoration.

This is the implemented Operate-mode reference. Native Windows behavior and the user's Fluent/system-type choice are visual authority. The landing view presents the next study action, local resources and recent activity. Other surfaces retain the same practical hierarchy rather than repeating a landing-page composition.

**Key Characteristics:**
- Native Fluent controls and system theme.
- Dense tables, labeled property groups and expandable run evidence.
- Vietnamese task language with technical identifiers preserved.
- Scientific plots and raw data traceable to the selected run.

## Colors

The application imports `XamlControlsResources` and inherits native theme brushes and control states. Accent buttons identify principal actions; navigation uses the Fluent selection indicator. No application-specific fixed palette or tonal ramp is defined. Inspected captures show the light system theme; dark theme has not been visually verified.

**The System Authority Rule.** Use native theme resources for chrome, text, focus, selection and controls; do not freeze screenshot colors into application tokens.

ScottPlot owns scientific series colors. Pareto uses dark orange open circles for the front and a separate series for eligible designs, with a legend. Preserve marker and legend distinctions alongside color.

## Typography

Use Windows system typography (Segoe UI Variable where supplied by the platform), inherited through native controls. Page headings use `TitleTextBlockStyle`; section headings use `SubtitleTextBlockStyle`. Evidence labels are semibold, values selectable and sources smaller supporting text. Resource summaries use the explicit resource-summary role. JSON, logs, activity and backup diagnostics use Consolas.

**The Readable Evidence Rule.** Keep labels, values, units and sources visible together. Preserve full identifiers through wrapping, tooltips or selectable raw detail rather than relying on a truncated label.

## Layout

The window initially requests 1550 × 1050 physical pixels. A global `InfoBar` sits above the left `NavigationView`; its open pane is 230 effective pixels. Workspace padding is horizontal workspace spacing and vertical group spacing. Native XAML dimensions are effective pixels; portable frontmatter records the observed numeric scale as px.

Five navigation surfaces are implemented:

- **Tổng quan:** study action, resource summary, then scrollable recent activity.
- **Tạo job:** horizontally scrollable sampling controls, filling tab workspace and bottom creation actions. Model expanders use label/editor/source columns (310 / 240 / remaining width). Tabs separate model inputs, sweep axes, resolved preview, advanced JSON and job limits.
- **Job mô phỏng:** batch list, job toolbar, run table, then selected-run actions and tabbed detail. The run table has a 1200 minimum width with horizontal scrolling. Expanding detail hides the batch/run lists and gives the evidence workspace their room; the same action restores the table.
- **Thư viện dữ liệu:** search and quality filter, multi-select run list, horizontally scrollable dataset fields/actions, then export-result and Pareto tabs. The result pane begins with a concrete export instruction.
- **Backup và cài đặt:** one vertical scrolling stack capped at 1050 wide. Configuration, Drive, upload resume and checksum restore fields/actions are stacked, including complete Drive ID and SHA-256 inputs.

**The Preserve Columns Rule.** Let wide scientific tables and toolbars scroll horizontally. Retain clear label/value/unit relationships as the window narrows. There is no mobile or web breakpoint system.

## Elevation & Depth

Depth comes from native Fluent surfaces, selected rows, tabs and control borders. The work area remains flat and quiet. Native dialogs supply modal treatment; no custom shadow vocabulary or ornamental card layer exists.

## Shapes

Control corners, strokes and focus treatment come from WinUI defaults. Do not introduce a separate radius system. Lists, grids, expanders and tab panels establish structure instead of decorative containers.

## Components

- **Actions:** native `Button`, with `AccentButtonStyle` for principal create/resume actions. Stop, stop-after-current and retry are distinct labeled actions. Retain platform hover, pressed, focus and disabled states.
- **Inputs:** native `NumberBox`, `TextBox`, `ComboBox` and `CheckBox`. Generated model inputs show units when defined and source text; automation label, name and help text derive from the visible label and descriptor. Fixed/preset-controlled values remain readable while disabled or read-only.
- **Navigation and tabs:** native `NavigationView` with icons/text and nonclosable `TabViewItem` panels. Tab content stretches to fill the workspace. Run tabs cannot be dragged or reordered.
- **Run evidence:** separate native lists for actual inputs, results/quality and attempts. Each row has label/value/unit columns and a full-width provenance line. Complete JSON has a separate tab. Selected run identity remains above its actions.
- **Progress and feedback:** measured progress uses native `ProgressBar`; unknown progress is indeterminate. Text exposes state, phase, timing and attempt count. Global errors use `InfoBar` and direct users to fuller detail/logs. Missing outputs, figures and plots explain the next available step.
- **Scientific views:** ScottPlot supplies force–time, force–displacement, displacement–time and energy–time curves with axis labels and units. Energy series have a legend. Plot titles identify raw selected-run data. Pareto compares matching load groups and explicitly withholds physical-validation claims. Simulation images form a scrollable gallery with filenames; they are generated evidence.

**The Trace Before Polish Rule.** Preserve raw provenance and scientific meaning when changing presentation. Keep display decimation separate from export samples. Physical deformation scale 1 and labeled frame times remain contour requirements; the inspected desktop captures do not establish those rendering details.

## Do's and Don'ts

### Do:
- Do extend native Fluent controls, system typography and theme resources.
- Do keep units, sources, numerical status and attempt context near their values.
- Do preserve horizontal access to wide data/actions and vertical access to all settings.
- Do retain scientific labels, raw-data context and physical-validation qualifications.
- Do verify keyboard, assistive-technology and theme behavior when those areas change.

### Don't:
- Don't replace structured input/output/attempt lists with a JSON-only inspector.
- Don't encode run status or scientific identity only in color.
- Don't equate solver completion or numerical eligibility with physical validation.
- Don't replace the native Windows world with web styling, custom fonts or raster interface mockups.

<!-- Evidence: MainWindow.xaml, MainWindow.xaml.cs, App.xaml; output/ui/review-input-fixed.png, review-settings-fixed.png, review-restore-fixed.png, review-library-fixed.png and jobs-chart-final.png. Current source supersedes older chart capture tab labels. Reviewer disposition: ship after five material fixes. Actual assistive-technology use and dark-theme appearance were not tested. -->

The Vercel web extension has a separate responsive specification in [web/DESIGN.md](web/DESIGN.md). Native-only statements above apply to WinUI and do not override the web breakpoint system.
