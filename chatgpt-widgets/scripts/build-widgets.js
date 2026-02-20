/**
 * Build script for ChatGPT widgets.
 *
 * Compiles each widget to a self-contained HTML bundle.
 */

import * as esbuild from 'esbuild';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, '..');
const srcDir = path.join(rootDir, 'src');
const distDir = path.join(rootDir, 'dist');
const widgetsDir = path.join(srcDir, 'widgets');

// List of widgets to build
const widgets = [
  'PropertySearchWidget',
  'PropertyDetailsWidget',
  'PropertySwipeWidget',
  'VisitSchedulerWidget',
  'VisitListWidget',
  'LeaseDetailsWidget',
  'MaintenanceWidget',
  'OwnerDashboardWidget',
  // Property Management Widgets
  'LeaseManagementWidget',
  'RentCollectionWidget',
  'TenantRentWidget',
];

// CSS reset and base styles
const baseStyles = `
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}
body {
  font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  background:
    radial-gradient(circle at 18% 0%, rgba(229, 208, 139, 0.18), transparent 46%),
    radial-gradient(circle at 84% 100%, rgba(61, 56, 41, 0.08), transparent 52%);
}
img {
  max-width: 100%;
  height: auto;
}
button {
  cursor: pointer;
  font-family: inherit;
}
#root {
  animation: widgetFadeIn 220ms ease-out;
}
@keyframes widgetFadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
`;

/**
 * Generate HTML wrapper for widget bundle
 * @param {string} widgetName
 * @param {string} bundleJs
 * @returns {string}
 */
function generateHtml(widgetName, bundleJs) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${widgetName}</title>
  <style>${baseStyles}</style>
</head>
<body>
  <div id="root"></div>
  <script>${bundleJs}</script>
</body>
</html>`;
}

/**
 * Build a single widget
 * @param {string} widgetName
 * @param {boolean} watch
 */
async function buildWidget(widgetName, watch = false) {
  const entryPoint = path.join(widgetsDir, `${widgetName}.tsx`);

  if (!fs.existsSync(entryPoint)) {
    console.log(`⏭️  Skipping ${widgetName} (file not found)`);
    return;
  }

  const outfile = path.join(distDir, `${widgetName}.js`);

  /** @type {import('esbuild').BuildOptions} */
  const buildOptions = {
    entryPoints: [entryPoint],
    bundle: true,
    minify: !watch,
    outfile,
    format: 'iife',
    target: 'es2020',
    jsx: 'automatic',
    loader: {
      '.tsx': 'tsx',
      '.ts': 'ts',
    },
    define: {
      'process.env.NODE_ENV': watch ? '"development"' : '"production"',
    },
  };

  if (watch) {
    const ctx = await esbuild.context(buildOptions);
    await ctx.watch();
    console.log(`👀 Watching ${widgetName}...`);
  } else {
    await esbuild.build(buildOptions);

    // Read the bundled JS and create HTML
    const bundleJs = fs.readFileSync(outfile, 'utf-8');
    const html = generateHtml(widgetName, bundleJs);
    const htmlPath = path.join(distDir, `${widgetName}.html`);
    fs.writeFileSync(htmlPath, html);

    // Clean up the intermediate JS file
    fs.unlinkSync(outfile);

    console.log(`✅ Built ${widgetName}.html`);
  }
}

async function main() {
  const watch = process.argv.includes('--watch');

  // Ensure dist directory exists
  if (!fs.existsSync(distDir)) {
    fs.mkdirSync(distDir, { recursive: true });
  }

  console.log(`🔨 Building ${widgets.length} widgets...`);

  for (const widget of widgets) {
    await buildWidget(widget, watch);
  }

  if (!watch) {
    console.log('\n🎉 Build complete!');
  }
}

main().catch((err) => {
  console.error('Build failed:', err);
  process.exit(1);
});
