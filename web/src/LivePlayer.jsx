import { useEffect, useRef, useState } from 'react'

const ORIGIN = 'https://www.youtube.com'

/** A player without YouTube's own UI.
 *
 *  `controls=0` removes the bottom control bar (and the YouTube logo in it).
 *  The rest of the overlay - title, share, watch-later - only appears on
 *  hover/pause, so a transparent shield on top keeps the mouse away entirely.
 *
 *  `modestbranding` is not used - YouTube deprecated it in 2023.
 *
 *  Mute/unmute goes through `enablejsapi=1` + postMessage. That avoids loading
 *  YouTube's iframe_api script - one less external dependency, and the video
 *  starts without waiting for that script to arrive.
 */
export default function LivePlayer({ videoId, title }) {
  const wrap = useRef(null)     // .frame - fullscreen applies to this
  const frame = useRef(null)
  const [muted, setMuted] = useState(true)
  const [paused, setPaused] = useState(false)
  const [note, setNote] = useState(null)   // null | 'ended' | 'error'

  const src =
    `${ORIGIN}/embed/${videoId}?` +
    new URLSearchParams({
      autoplay: '1',
      mute: '1',          // browsers refuse autoplay unless muted
      controls: '0',
      rel: '0',
      fs: '0',            // fullscreen via our own button
      disablekb: '1',
      playsinline: '1',
      iv_load_policy: '3',
      enablejsapi: '1',
    })

  const send = (func, args = []) => {
    frame.current?.contentWindow?.postMessage(
      JSON.stringify({ event: 'command', func, args }),
      ORIGIN,
    )
  }

  // Listen for ended/error from the player. Best-effort - if the messages never
  // arrive, the video still plays exactly the same.
  // (Player passes key={stream.id}, so this component remounts when the cam
  //  changes - no need to reset state by hand.)
  useEffect(() => {
    const onMessage = (e) => {
      if (e.origin !== ORIGIN || e.source !== frame.current?.contentWindow) return
      let d = e.data
      if (typeof d === 'string') {
        try {
          d = JSON.parse(d)
        } catch {
          return
        }
      }
      if (d?.event === 'onError') setNote('error')
      else if (d?.event === 'onStateChange' && d.info === 0) setNote('ended')
    }

    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [videoId])

  // Handshake once the iframe is ready - only then does the player send events
  const onLoad = () => {
    frame.current?.contentWindow?.postMessage(
      JSON.stringify({ event: 'listening', id: videoId }),
      ORIGIN,
    )
  }

  const toggleMute = () => {
    if (muted) {
      send('unMute')
      send('setVolume', [60])
    } else {
      send('mute')
    }
    setMuted(!muted)
  }

  // The shield keeps the mouse off the player, so pause is ours to handle too
  const togglePlay = () => {
    send(paused ? 'playVideo' : 'pauseVideo')
    setPaused(!paused)
  }

  const toggleFullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen()
    else wrap.current?.requestFullscreen?.()
  }

  return (
    <div className="frame" ref={wrap}>
      <iframe
        ref={frame}
        src={src}
        onLoad={onLoad}
        title={title}
        allow="autoplay; encrypted-media; picture-in-picture"
        referrerPolicy="strict-origin-when-cross-origin"
      />
      {/* Keeps mouse/tap off the player, so YouTube's overlay never shows */}
      <div className="frame-shield" />

      {note === 'ended' && (
        <div className="frame-note">
          This stream has ended - it will drop off the list at the next refresh.
        </div>
      )}
      {note === 'error' && (
        <div className="frame-note">
          This cam cannot play here.{' '}
          <a href={`https://www.youtube.com/watch?v=${videoId}`} target="_blank" rel="noreferrer">
            Watch on YouTube ↗
          </a>
        </div>
      )}

      <div className="frame-bar">
        <button onClick={togglePlay} title={paused ? 'Play' : 'Pause'}>
          {paused ? '▶' : '❚❚'}
        </button>
        <span className="frame-live">{paused ? '❙ Paused' : '● LIVE'}</span>
        <span className="frame-title">{title}</span>
        <button onClick={toggleMute} title={muted ? 'Unmute' : 'Mute'}>
          {muted ? '🔇' : '🔊'}
        </button>
        <button onClick={toggleFullscreen} title="Fullscreen">
          ⛶
        </button>
      </div>
    </div>
  )
}
