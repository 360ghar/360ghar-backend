/**
 * Test shim for `react-dom/client`. A widget calls createRoot(...).render(<Widget />) when it
 * loads. The shim keeps the element and renders it to HTML with the renderer in the same
 * bundle, so one React copy serves the widget and the renderer.
 */

import { renderToStaticMarkup } from 'react-dom/server';

export function createRoot() {
  return {
    render(node) {
      globalThis.__renderWidget = () => renderToStaticMarkup(node);
    },
  };
}
