import { useEffect, useMemo, useState } from 'react'
import {
  Activity, ArrowDownRight, ArrowUpRight, BarChart3, ChevronDown, Expand,
  Gem, Globe2, Layers3, RefreshCw, Search, Star, X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useMarketData } from '@/hooks/useMarketData'
import './Heatmap.css'

type Market = 'ALL' | 'INDIA' | 'GLOBAL' | 'COMMODITY'
type AssetType = 'company' | 'commodity' | 'index'
type Period = '1D' | '1W' | '1M' | '3M' | '1Y'

interface Asset {
  symbol: string
  exchange: string
  name: string
  asset_type: AssetType
  market: Market
  sector?: string | null
  country?: string | null
  currency?: string | null
  last_price?: number | null
  previous_close?: number | null
  change_value?: number | null
  change_percent?: number | null
  volume?: number | null
  market_cap?: number | null
  reference_market_cap?: number | null
  source?: string | null
  as_of?: string | null
}

interface Candle {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume?: number | null
}

const API = '/market-heatmap/api'
const PERIODS: Period[] = ['1D', '1W', '1M', '3M', '1Y']

const INDIA_FEED_SYMBOLS = [
  'RELIANCE', 'TCS', 'HDFCBANK', 'ICICIBANK', 'INFY', 'BHARTIARTL', 'SBIN',
  'ITC', 'LT', 'HINDUNILVR', 'AXISBANK', 'KOTAKBANK', 'BAJFINANCE', 'MARUTI',
  'SUNPHARMA', 'TITAN', 'NTPC', 'POWERGRID', 'ONGC', 'TATAMOTORS', 'M&M',
  'ULTRACEMCO', 'ADANIENT', 'ASIANPAINT', 'WIPRO', 'HCLTECH', 'NESTLEIND', 'JSWSTEEL',
].map(symbol => ({ symbol, exchange: 'NSE' })).concat([
  { symbol: 'NIFTY', exchange: 'NSE_INDEX' },
  { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX' },
  { symbol: 'SENSEX', exchange: 'BSE_INDEX' },
]);


const fmtPrice = (value?: number | null, currency?: string | null) => {
  if (value == null || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat(currency === 'INR' || currency === '₹' ? 'en-IN' : 'en-US', { style: 'currency', currency: currency === 'INR' || currency === '₹' ? 'INR' : 'USD', maximumFractionDigits: 2 }).format(value)
}
const fmtPct = (value?: number | null) => value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
const tileTone = (value?: number | null) => {
  if (value == null) return 'heat-tile-neutral'
  if (value >= 2) return 'heat-tile-strong-up'
  if (value > 0) return 'heat-tile-up'
  if (value <= -1) return 'heat-tile-strong-down'
  return 'heat-tile-down'
}
const queryString = (values: Record<string, string>) => new URLSearchParams(values).toString()

function HeatTile({ asset, selected, onSelect, compact = false, sizeBy = 'market_cap' }: {
  asset: Asset; selected: boolean; onSelect: () => void; compact?: boolean; sizeBy?: string
}) {
  const weight = asset.market_cap ?? asset.reference_market_cap ?? 0
  const span = !compact && sizeBy === 'market_cap' && weight > 1_000_000_000_000 ? 2 : 1
  return (
    <button
      type="button"
      onClick={onSelect}
      title={`${asset.name} · ${fmtPrice(asset.last_price, asset.currency)} · ${fmtPct(asset.change_percent)}`}
      className={cn('heat-tile', tileTone(asset.change_percent), selected && 'heat-tile-selected', compact && 'heat-tile-compact')}
      style={{ gridColumn: `span ${span}` }}
    >
      <span className="heat-tile-symbol">{asset.symbol}</span>
      <span className="heat-tile-name">{asset.name}</span>
      <strong className="heat-tile-change">{fmtPct(asset.change_percent)}</strong>
      <span className="heat-tile-price">{fmtPrice(asset.last_price, asset.currency)}</span>
    </button>
  )
}

function MiniChart({ candles }: { candles: Candle[] }) {
  if (candles.length < 2) {
    return <div className="heat-chart-empty"><BarChart3 size={20} /> Historical candles will appear here after data ingestion.</div>
  }
  const values = candles.map(c => c.close)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const points = values.map((value, index) => `${(index / (values.length - 1)) * 100},${94 - ((value - min) / range) * 82}`).join(' ')
  return (
    <svg className="heat-chart-svg" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Historical closing prices">
      {[20, 40, 60, 80].map(y => <line key={y} x1="0" x2="100" y1={y} y2={y} className="heat-chart-grid" />)}
      <polyline points={points} className="heat-chart-line" />
    </svg>
  )
}

export default function Heatmap() {
  const [assets, setAssets] = useState<Asset[]>([])
  const [commodityData, setCommodityData] = useState<Asset[]>([])
  const [indexData, setIndexData] = useState<Asset[]>([])
  const [movers, setMovers] = useState<Asset[]>([])
  const [candles, setCandles] = useState<Candle[]>([])
  const [market, setMarket] = useState<'INDIA' | 'GLOBAL'>('GLOBAL')
  const [view, setView] = useState<'companies' | 'commodities'>('companies')
  const [groupBy, setGroupBy] = useState('sector')
  const [sizeBy, setSizeBy] = useState('market_cap')
  const [period, setPeriod] = useState<Period>('1D')
  const [sideMode, setSideMode] = useState<'commodities' | 'movers'>('commodities')
  const [moverMarket, setMoverMarket] = useState<'INDIA' | 'GLOBAL'>('INDIA')
  const [moverDirection, setMoverDirection] = useState<'gainers' | 'losers'>('gainers')
  const [selected, setSelected] = useState<Asset | null>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [detailTab, setDetailTab] = useState('Overview')
  const [watchlisted, setWatchlisted] = useState(false)
  const [watchlistBusy, setWatchlistBusy] = useState(false)
  const [streamStatus, setStreamStatus] = useState('stopped')
  const indiaFeed = useMarketData({ symbols: INDIA_FEED_SYMBOLS, mode: 'Quote', enabled: market === 'INDIA' || moverMarket === 'INDIA' })

  const loadSnapshot = async (quiet = false) => {
    if (quiet) setRefreshing(true); else setLoading(true)
    setError('')
    try {
      const [companyResponse, commodityResponse, indexResponse] = await Promise.all([
        fetch(`${API}/snapshot?${queryString({ market, asset_type: view === 'companies' ? 'COMPANY' : 'COMMODITY', period })}`, { credentials: 'same-origin' }),
        fetch(`${API}/snapshot?${queryString({ market: 'COMMODITY', asset_type: 'COMMODITY', period })}`, { credentials: 'same-origin' }),
        fetch(`${API}/snapshot?${queryString({ market: 'ALL', asset_type: 'INDEX', period })}`, { credentials: 'same-origin' }),
      ])
      if (!companyResponse.ok || !commodityResponse.ok || !indexResponse.ok) throw new Error('Unable to load market heatmap data. Please sign in again or retry.')
      const [companyPayload, commodityPayload, indexPayload] = await Promise.all([companyResponse.json(), commodityResponse.json(), indexResponse.json()])
      const list: Asset[] = companyPayload.data ?? []
      const commodities: Asset[] = commodityPayload.data ?? []
      const indices: Asset[] = indexPayload.data ?? []
      setCommodityData(commodities)
      setIndexData(indices)
      setAssets(view === 'companies' ? list.filter(a => a.asset_type !== 'index') : commodities)
      if (!selected) {
        const initial = view === 'companies' ? list.find(a => a.asset_type === 'company') ?? list[0] : commodities[0]
        if (initial) setSelected(initial)
      }
      if (selected) {
        const updated = [...list, ...commodities, ...indices].find(a => a.symbol === selected.symbol && a.exchange === selected.exchange)
        if (updated) setSelected(updated)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Market data request failed')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  const loadMovers = async () => {
    try {
      const response = await fetch(`${API}/movers?${queryString({ market: moverMarket, direction: moverDirection, limit: '8' })}`, { credentials: 'same-origin' })
      if (response.ok) {
        const payload = await response.json()
        setMovers(payload.data ?? [])
      }
    } catch { /* The main heatmap remains usable when movers are unavailable. */ }
  }

  const loadHistory = async (asset: Asset | null) => {
    if (!asset) { setCandles([]); return }
    try {
      const timeframe = period === '1D' ? '5M' : period === '1W' ? '1H' : '1D'
      const response = await fetch(`${API}/instruments/${encodeURIComponent(asset.symbol)}/history?${queryString({ exchange: asset.exchange, timeframe, limit: '250' })}`, { credentials: 'same-origin' })
      if (!response.ok) { setCandles([]); return }
      const payload = await response.json()
      setCandles(payload.data ?? [])
    } catch { setCandles([]) }
  }

  const addSelectedToWatchlist = async () => {
    if (!selected || !selected.exchange || watchlistBusy) return
    setWatchlistBusy(true)
    setError('')
    try {
      const requestOptions = { credentials: 'same-origin' as RequestCredentials }
      const listsResponse = await fetch('/watchlist/api/lists', requestOptions)
      if (!listsResponse.ok) throw new Error('Could not load your watchlists')
      let listsPayload = await listsResponse.json()
      let target = (listsPayload.data ?? [])[0]
      if (!target) {
        const createResponse = await fetch('/watchlist/api/lists', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: 'Heatmap' }),
        })
        if (createResponse.ok) {
          const created = await createResponse.json()
          target = created.data
        } else {
          const retry = await fetch('/watchlist/api/lists', requestOptions)
          listsPayload = await retry.json()
          target = (listsPayload.data ?? []).find((list: { name: string }) => list.name === 'Heatmap') ?? (listsPayload.data ?? [])[0]
        }
      }
      if (!target) throw new Error('Create a watchlist before adding instruments')
      const exists = (target.items ?? []).some((item: { symbol: string; exchange: string }) =>
        item.symbol === selected.symbol && item.exchange === selected.exchange
      )
      if (!exists) {
        const addResponse = await fetch(`/watchlist/api/lists/${target.id}/items`, {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol: selected.symbol, exchange: selected.exchange }),
        })
        if (!addResponse.ok) throw new Error('Could not add this instrument to the watchlist')
      }
      setWatchlisted(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Watchlist update failed')
    } finally {
      setWatchlistBusy(false)
    }
  }

  const refreshMarketData = async () => {
    setRefreshing(true)
    try {
      const response = await fetch(`${API}/refresh`, { credentials: 'same-origin' })
      const payload = await response.json()
      if (!response.ok || payload.status !== 'success') throw new Error(payload.message || 'Market refresh failed')
      setStreamStatus(payload.providers?.global?.stream?.status ?? 'not_configured')
      await Promise.all([loadSnapshot(true), loadMovers(), selected ? loadHistory(selected) : Promise.resolve()])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Market data refresh failed')
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    if (!indiaFeed.data.size) return
    const liveQuotes = Array.from(indiaFeed.data.values())
    const mergeLive = (asset: Asset): Asset => {
      const tick = liveQuotes.find(item => item.exchange === asset.exchange && item.symbol === asset.symbol)
      if (!tick) return asset
      const quote = tick.data
      const previousClose = quote.close ?? asset.previous_close
      const changeValue = quote.change ?? (quote.ltp != null && previousClose != null ? quote.ltp - previousClose : asset.change_value)
      const changePercent = quote.change_percent ?? (quote.ltp != null && previousClose ? ((quote.ltp / previousClose) - 1) * 100 : asset.change_percent)
      return {
        ...asset,
        last_price: quote.ltp ?? asset.last_price,
        previous_close: previousClose,
        change_value: changeValue,
        change_percent: changePercent,
        volume: quote.volume ?? asset.volume,
      }
    }
    setAssets(previous => previous.map(mergeLive))
    setMovers(previous => previous.map(mergeLive))
    setSelected(previous => previous ? mergeLive(previous) : previous)
    setIndexData(previous => previous.map(mergeLive))
  }, [indiaFeed.data])

  useEffect(() => { setWatchlisted(false) }, [selected?.symbol, selected?.exchange])

  useEffect(() => { void loadSnapshot() }, [market, view, period])
  useEffect(() => { const timer = window.setInterval(() => { void loadSnapshot(true); void loadMovers() }, 10000); return () => window.clearInterval(timer) }, [market, view, period, moverMarket, moverDirection])
  useEffect(() => { const poll = async () => { try { const response = await fetch(`${API}/status`, { credentials: 'same-origin' }); const payload = await response.json(); setStreamStatus(payload.data?.twelvedata?.status ?? 'stopped') } catch { setStreamStatus('disconnected') } }; void poll(); const timer = window.setInterval(poll, 10000); return () => window.clearInterval(timer) }, [])
  useEffect(() => { void refreshMarketData(); const timer = window.setInterval(() => void refreshMarketData(), 7200000); return () => window.clearInterval(timer) }, [])
  useEffect(() => { void loadMovers() }, [moverMarket, moverDirection])
  useEffect(() => { void loadHistory(selected) }, [selected?.symbol, selected?.exchange, period])

  const filteredAssets = useMemo(() => assets.filter(asset =>
    `${asset.symbol} ${asset.name} ${asset.sector ?? ''}`.toLowerCase().includes(query.toLowerCase())
  ), [assets, query])

  const grouped = useMemo(() => {
    const map = new Map<string, Asset[]>()
    filteredAssets.forEach(asset => {
      const key = groupBy === 'sector' ? asset.sector || 'Other' : groupBy === 'market' ? asset.market : asset.country || 'Other'
      map.set(key, [...(map.get(key) ?? []), asset])
    })
    return [...map.entries()]
  }, [filteredAssets, groupBy])

  const commodityAssets = commodityData
  const indices = indexData.filter(index => market === 'INDIA' ? index.market === 'INDIA' : index.market === 'GLOBAL')
  const indiaLive = Array.from(indiaFeed.data.values()).some(item => item.updateSource === 'websocket' && item.lastUpdate != null && Date.now() - item.lastUpdate < 60000)
  const marketStatus = (streamStatus === 'live' && market === 'GLOBAL') || (indiaLive && market === 'INDIA') ? 'LIVE' : [...assets, ...commodityData, ...indexData].some(a => a.last_price != null) ? 'Data available' : 'Waiting for provider data'

  return (
    <div className={cn('heatmap-page', expanded && 'heatmap-expanded')}>
      <div className="heatmap-heading">
        <div className="heatmap-title"><span className="heatmap-globe">🌐</span><div><h1>Global Market Heatmap</h1><p>World equities and commodities · Interactive market overview</p></div><span className={cn('heat-live-pill', marketStatus === 'LIVE' ? 'is-live' : 'is-waiting')}><i />{marketStatus}</span></div>
        <div className="heatmap-heading-actions"><span className="heat-clock">UTC +05:30 · {new Date().toLocaleString()}</span><button className="heat-icon-button" onClick={() => void refreshMarketData()} title="Refresh market data"><RefreshCw size={16} className={refreshing ? 'heat-spin' : ''} /></button></div>
      </div>

      <div className="heat-index-strip">
        {indices.length ? indices.slice(0, 6).map(index => (
          <div className="heat-index-card" key={index.symbol}><span className="heat-index-flag">{index.country === 'India' ? '🇮🇳' : '🌐'}</span><div><b>{index.name}</b><strong>{fmtPrice(index.last_price, index.currency)}</strong></div><em className={index.change_percent != null && index.change_percent < 0 ? 'negative' : 'positive'}>{fmtPct(index.change_percent)}</em></div>
        )) : ['S&P 500', 'NASDAQ', 'DOW', 'FTSE 100', 'DAX', 'Nikkei 225'].map(name => (
          <div className="heat-index-card heat-index-empty" key={name}><span className="heat-index-flag">◎</span><div><b>{name}</b><strong>Awaiting data</strong></div><em>—</em></div>
        ))}
      </div>

      <div className="heat-toolbar">
        <div className="heat-view-switch">
          <button className={view === 'companies' ? 'active' : ''} onClick={() => setView('companies')}>World Companies</button>
          <button className={view === 'commodities' ? 'active' : ''} onClick={() => setView('commodities')}>Commodities</button>
        </div>
        <label className="heat-select-label">Market <select value={market} onChange={e => setMarket(e.target.value as 'INDIA' | 'GLOBAL')}><option value="GLOBAL">Global</option><option value="INDIA">India</option></select><ChevronDown size={13} /></label>
        <label className="heat-select-label">Group by <select value={groupBy} onChange={e => setGroupBy(e.target.value)}><option value="sector">Sector</option><option value="market">Market</option><option value="country">Country</option></select><ChevronDown size={13} /></label>
        <label className="heat-select-label">Size by <select value={sizeBy} onChange={e => setSizeBy(e.target.value)}><option value="market_cap">Market Cap</option><option value="equal">Equal</option></select><ChevronDown size={13} /></label>
        <label className="heat-select-label">Period <select value={period} onChange={e => setPeriod(e.target.value as Period)}>{PERIODS.map(p => <option key={p}>{p}</option>)}</select><ChevronDown size={13} /></label>
        <div className="heat-toolbar-search"><Search size={14} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Find a company" /></div>
        <button className="heat-icon-button" onClick={() => setExpanded(v => !v)} title={expanded ? 'Exit expanded view' : 'Expand heatmap'}>{expanded ? <X size={17} /> : <Expand size={17} />}</button>
      </div>

      {error && <div className="heat-error" role="alert">{error}</div>}
      <div className="heat-main-grid">
        <section className="heat-sector-grid" aria-label="Company heatmap">
          {loading ? <div className="heat-empty-state"><Activity className="heat-spin" /> Loading market data…</div> :
            grouped.length ? grouped.map(([group, items]) => {
              const validChanges = items.map(a => a.change_percent).filter((v): v is number => v != null)
              const average = validChanges.length ? validChanges.reduce((sum, v) => sum + v, 0) / validChanges.length : null
              return <section className="heat-sector-card" key={group}>
                <header><b>{group}</b><strong className={average != null && average < 0 ? 'negative' : 'positive'}>{fmtPct(average)}</strong></header>
                <div className="heat-sector-tiles">
                  {items.map(asset => <HeatTile key={`${asset.exchange}:${asset.symbol}`} asset={asset} selected={selected?.symbol === asset.symbol && selected.exchange === asset.exchange} onSelect={() => setSelected(asset)} sizeBy={sizeBy} />)}
                </div>
              </section>
            }) : <div className="heat-empty-state"><Layers3 size={24} /><b>No market instruments yet</b><span>Once a market-data provider is connected and its instruments are ingested, they will appear here. No sample prices are shown.</span></div>
          }
        </section>

        <aside className="heat-side-panel">
          <div className="heat-side-heading"><h2><span>▥</span> {sideMode === 'commodities' ? 'Commodities' : 'Market Movers'}</h2><div className="heat-side-tabs"><button className={sideMode === 'commodities' ? 'active' : ''} onClick={() => setSideMode('commodities')}>Commodities</button><button className={sideMode === 'movers' ? 'active' : ''} onClick={() => setSideMode('movers')}>Movers</button></div></div>
          {sideMode === 'commodities' ? <>
            <div className="heat-commodity-tiles">{commodityAssets.length ? commodityAssets.slice(0, 8).map(asset => <HeatTile key={asset.symbol} asset={asset} selected={selected?.symbol === asset.symbol} onSelect={() => setSelected(asset)} compact />) : <div className="heat-side-empty"><Gem size={20} /> Commodity quotes will appear after provider ingestion.</div>}</div>
            <div className="heat-commodity-table"><div className="heat-table-head"><span>Commodity</span><span>Price</span><span>1D %</span></div>{commodityAssets.slice(0, 6).map(asset => <button key={asset.symbol} onClick={() => setSelected(asset)}><span>{asset.name} ({asset.symbol})</span><b>{fmtPrice(asset.last_price, asset.currency)}</b><strong className={asset.change_percent != null && asset.change_percent < 0 ? 'negative' : 'positive'}>{fmtPct(asset.change_percent)}</strong></button>)}</div>
          </> : <>
            <div className="heat-mover-controls"><select value={moverMarket} onChange={e => setMoverMarket(e.target.value as 'INDIA' | 'GLOBAL')}><option value="INDIA">Indian markets</option><option value="GLOBAL">Global markets</option></select><button className={moverDirection === 'gainers' ? 'active' : ''} onClick={() => setMoverDirection('gainers')}><ArrowUpRight size={13} /> Gainers</button><button className={moverDirection === 'losers' ? 'active' : ''} onClick={() => setMoverDirection('losers')}><ArrowDownRight size={13} /> Losers</button></div>
            <div className="heat-mover-list">{movers.length ? movers.map((asset, index) => <button key={asset.symbol} onClick={() => setSelected(asset)}><span className="heat-mover-rank">{index + 1}</span><span><b>{asset.symbol}</b><small>{asset.name}</small></span><strong className={asset.change_percent != null && asset.change_percent < 0 ? 'negative' : 'positive'}>{fmtPct(asset.change_percent)}</strong></button>) : <div className="heat-side-empty">No mover data available yet.</div>}</div>
          </>}
        </aside>
      </div>

      <section className="heat-detail-panel">
        <div className="heat-instrument-summary">
          {selected ? <>
            <div className="heat-instrument-market">{selected.market === 'INDIA' ? '🇮🇳 Indian market' : selected.market === 'COMMODITY' ? '🪙 Commodity' : '🌐 Global market'} · {selected.sector || selected.asset_type}</div>
            <div className="heat-instrument-name"><b>{selected.symbol}</b><span>{selected.name}</span></div>
            <div className="heat-instrument-price">{fmtPrice(selected.last_price, selected.currency)}</div>
            <div className={cn('heat-instrument-change', selected.change_percent != null && selected.change_percent < 0 ? 'negative' : 'positive')}>{selected.change_value == null ? '—' : fmtPrice(Math.abs(selected.change_value), selected.currency)} ({fmtPct(selected.change_percent)})</div>
            <div className="heat-instrument-stats"><span><small>Market Cap</small><b>{selected.market_cap ? fmtPrice(selected.market_cap, selected.currency) : '—'}</b></span><span><small>Volume</small><b>{selected.volume?.toLocaleString() ?? '—'}</b></span><span><small>Exchange</small><b>{selected.exchange || '—'}</b></span></div>
          </> : <div className="heat-detail-no-selection">Select a company or commodity to inspect its market data.</div>}
        </div>
        <div className="heat-chart-panel"><div className="heat-chart-periods">{PERIODS.map(p => <button key={p} className={period === p ? 'active' : ''} onClick={() => setPeriod(p)}>{p}</button>)}</div><MiniChart candles={candles} /><div className="heat-chart-axis"><span>Historical OHLCV</span><span>{candles.length} candles stored</span></div></div>
        <div className="heat-company-panel">
          <div className="heat-detail-tabs">{['Overview', 'News', 'Financials', 'Technicals'].map(tab => <button key={tab} className={detailTab === tab ? 'active' : ''} onClick={() => setDetailTab(tab)}>{tab}</button>)}</div>
          {selected ? <><p>{detailTab === 'Overview' ? `${selected.name} market overview. Company description and fundamentals will be supplied by the reference-data provider.` : `${detailTab} data is not available until its provider integration is configured.`}</p><div className="heat-tags"><span>{selected.sector || selected.asset_type}</span><span>{selected.country || selected.market}</span></div><div className="heat-detail-actions"><button onClick={() => void addSelectedToWatchlist()} disabled={watchlistBusy}><Star size={14} fill={watchlisted ? 'currentColor' : 'none'} /> {watchlistBusy ? 'Adding…' : watchlisted ? 'Added to Watchlist' : 'Add to Watchlist'}</button><button onClick={() => window.location.assign(`/tradingview?symbol=${encodeURIComponent(selected.symbol)}&exchange=${encodeURIComponent(selected.exchange)}`)}>Open in Chart →</button></div></> : <p>Instrument fundamentals and company information will appear here.</p>}
        </div>
      </section>
      <footer className="heatmap-footnote"><span><Activity size={13} /> {marketStatus}</span><span>Source timestamp: {assets.find(a => a.as_of)?.as_of ?? 'No provider snapshot stored yet'}</span><span>SQLite market store</span></footer>
    </div>
  )
}
