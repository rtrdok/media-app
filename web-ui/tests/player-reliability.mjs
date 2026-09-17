// Run: npm exec --yes --package=playwright -- node tests/player-reliability.mjs
// Uses an installed Edge (or PLAYWRIGHT_BROWSER), isolated profile and mock APIs.
import assert from "node:assert/strict"
import { existsSync } from "node:fs"
import path from "node:path"
import { pathToFileURL } from "node:url"
import { createServer } from "vite"
import ts from "typescript"

const playwrightPath = (process.env.PATH || "").split(path.delimiter)
  .map((p) => path.resolve(p, "../playwright/index.mjs"))
  .find((p) => existsSync(p))
const { chromium } = await import(playwrightPath ? pathToFileURL(playwrightPath).href : "playwright")
const contextModule = `
import { createContext, useContext } from 'react';
export const TestContext = createContext(null);
export const useApp = () => useContext(TestContext);
`
const entry = `
import React, { useState, useCallback } from 'react';
import { createRoot } from 'react-dom/client';
import { TestContext } from '/src/context/AppProvider.tsx';
import { PlayerBar } from '/src/components/layout/PlayerBar.tsx';
import { InlineVideoPlayer } from '/src/components/media/InlineVideoPlayer.tsx';
import { playerTrackFromHistory } from '/src/lib/media.ts';
window.historyTrack = playerTrackFromHistory(${JSON.stringify({dest:'C:\\test.mp4',title:'test'})});
function Harness() {
  const [player,setPlayer] = useState(null);
  const [playing,setPlaying] = useState(false);
  const [page,setPage] = useState('library');
  const [preview,setPreview] = useState(false);
  const [mounted,setMounted] = useState(true);
  const [miniPlayer,setMiniPlayer] = useState(false);
  const closePlayer = useCallback(() => {setPlaying(false);setPlayer(null)}, []);
  Object.assign(window,{setTestPlayer:setPlayer,setTestPage:setPage,setPreview,setMounted});
  return <TestContext.Provider value={{page,player,setPlayer,playing,setPlaying,closePlayer,
    miniPlayer,setMiniPlayer,queueMeta:{length:0,index:0},repeat:'off',shuffle:false,
    playNextInQueue:()=>false,playPrevInQueue:()=>false,playQueue:[]}}>
    {mounted && <PlayerBar/>}
    {preview && <InlineVideoPlayer src='/fixture.wav'/>}
  </TestContext.Provider>;
}
createRoot(document.getElementById('root')).render(<React.StrictMode><Harness/></React.StrictMode>);
`
const server = await createServer({
  base: "/", server: { host: "127.0.0.1", port: 0, open: false },
  plugins: [{
    name: "player-test-harness", enforce: "pre",
    load(id) {
      if (id.replaceAll("\\", "/").endsWith("/src/context/AppProvider.tsx")) return contextModule
      if (id === "\0player-test.tsx") return ts.transpileModule(entry, {
        compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.ESNext },
      }).outputText
    },
    resolveId(id) { if (id === "/harness-entry.tsx") return "\0player-test.tsx" },
    configureServer(s) {
      s.middlewares.use("/player-test", async (_req, res) => {
        res.setHeader("Content-Type", "text/html")
        res.end(await s.transformIndexHtml('/player-test', '<div id="root"></div><script type="module" src="/harness-entry.tsx"></script>'))
      })
    },
  }],
})
let browser
try {
  await server.listen()
  browser = await chromium.launch(process.env.PLAYWRIGHT_BROWSER
    ? { executablePath: process.env.PLAYWRIGHT_BROWSER, headless: true }
    : { channel: "msedge", headless: true })
  const page = await browser.newPage()
  page.setDefaultTimeout(5000)
  const published = []
  await page.route("**/api/**", (route) => {
    if (route.request().url().includes("/api/player/publish")) {
      published.push(route.request().postDataJSON())
    }
    return route.fulfill({json:{ok:true,items:[],commands:[]}})
  })
  // Actual decodable media, not a mocked HTMLMediaElement.
  const wav = Buffer.alloc(44 + 16000)
  wav.write("RIFF"); wav.writeUInt32LE(wav.length - 8, 4); wav.write("WAVEfmt ", 8)
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22)
  wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28)
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write("data", 36)
  wav.writeUInt32LE(16000, 40)
  await page.route("**/fixture.wav", (route) => route.fulfill({contentType:"audio/wav",body:wav}))
  page.on("pageerror", (e) => console.error("Browser:", e.message))
  await page.goto(`${server.resolvedUrls.local[0]}player-test`)
  await page.waitForFunction(() => Boolean(window.setTestPlayer))
  const failures = []
  async function check(name, fn) {
    try { await fn(); console.log(`PASS ${name}`) }
    catch (e) { failures.push(name); console.error(`FAIL ${name}: ${e.message}`) }
  }
  await check("history track carries its local path", async () => {
    assert.equal(await page.evaluate(() => window.historyTrack.path), "C:\\test.mp4")
  })
  async function open(kind) {
    await page.evaluate((kind) => {
      window.setTestPage('library');window.setMounted(true);
      window.setTestPlayer({kind,src:'/fixture.wav',title:'Fixture'});
    }, kind)
    await page.waitForFunction(() => document.querySelector('audio,video')?.readyState >= 2)
    await page.evaluate(async () => {
      window.oldMedia = document.querySelector('audio,video')
      await window.oldMedia.play()
    })
    assert.equal(await page.evaluate(() => window.oldMedia.paused), false)
  }
  async function released() {
    await page.waitForFunction(() => !window.oldMedia.isConnected)
    const state = await page.evaluate(() => ({
      src:window.oldMedia.getAttribute('src'),ready:window.oldMedia.readyState,
      buffered:window.oldMedia.buffered.length,state:window.oldMedia.networkState,paused:window.oldMedia.paused,
    }))
    assert.equal(state.src, null)
    assert.equal(state.ready, 0)
    assert.equal(state.buffered, 0)
    assert.equal(state.paused, true)
    assert.ok([0, 3].includes(state.state), 'Media must be EMPTY or NO_SOURCE, not buffering')
  }
  for (const kind of ["audio", "video"]) {
    await check(`closing ${kind} unloads the detached element`, async () => {
      await open(kind)
      await page.getByRole('button',{name:'Закрыть трек',exact:true}).click()
      await released()
    })
  }
  await check("switching media kind unloads the previous element", async () => {
    await open('video')
    await page.evaluate(() => window.setTestPlayer({kind:'audio',src:'/fixture.wav',title:'Audio'}))
    await released()
  })
  await check("unmount unloads media", async () => {
    await open('video')
    await page.evaluate(() => window.setMounted(false))
    await released()
  })
  await check("settings hide releases media and return reloads it", async () => {
    await open('video')
    await page.evaluate(() => window.setTestPage('settings'))
    await released()
    await page.evaluate(() => window.setTestPage('library'))
    await page.waitForFunction(() => document.querySelector('video')?.readyState >= 2)
  })
  await check("inline preview unmount unloads media", async () => {
    await page.evaluate(() => {window.setTestPlayer(null);window.setPreview(true)})
    await page.waitForFunction(() => document.querySelector('video')?.readyState >= 2)
    await page.evaluate(() => {window.oldMedia=document.querySelector('video');window.setPreview(false)})
    await released()
  })
  await check("finished single track clears Discord Presence", async () => {
    await open('audio')
    await page.evaluate(() => document.querySelector('audio').dispatchEvent(new Event('ended')))
    await new Promise((resolve) => setTimeout(resolve, 50))
    assert.equal(published.at(-1)?.has_track, false)
  })
  assert.equal(failures.length, 0, `Failed: ${failures.join(', ')}`)
} finally {
  await browser?.close()
  await server.close()
}
