/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Where the backend lives. Leave unset in development — the Vite dev server
   * proxies /api, so the browser sees one origin and CORS never applies.
   */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
