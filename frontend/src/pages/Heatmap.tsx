import { useMemo, useState } from 'react'
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  ChevronDown,
  CircleDollarSign,
  Factory,
  Fuel,
  Gem,
  Globe2,
  Layers3,
  Search,
  SlidersHorizontal,
  Wheat,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

type Market = 'all' | 'india' | 'global' | 'commodities'
type AssetKind = 'company' | 'commodity'

interface HeatmapAsset {
  symbol: string
  name: string
  market: 'India' | 'Global' | 'Commodity'
  sector: string
  price: number
  change: number
  size: number
  kind: AssetKind
  currency: '₹' | '$'
}

const PREVIEW_ASSETS: HeatmapAsset[] = [
  { symbol: 'NVDA', name: 'NVIDIA', market: 'Global', sector: 'Technology', price: 503.12, change: 4.21, size: 9, kind: 'company', currency: '$' },
  { symbol: 'AAPL', name: 'Apple', market: 'Global', sector: 'Technology', price: 182.52, change: 3.08, size: 8, kind: 'company', currency: '$' },
  { symbol: 'MSFT', name: 'Microsoft', market: 'Global', sector: 'Technology', price: 421.34, change: 1.84, size: 8, kind: 'company', currency: '$' },
  { symbol: 'GOOGL', name: 'Alphabet', market: 'Global', sector: 'Communication', price: 141.23, change: 2.31, size: 6, kind: 'company', currency: '$' },
  { symbol: 'AMZN', name: 'Amazon', market: 'Global', sector: 'Consumer', price: 219.37, change: 2.49, size: 6, kind: 'company', currency: '$' },
  { symbol: 'TSLA', name: 'Tesla', market: 'Global', sector: 'Consumer', price: 338.11, change: -1.24, size: 5, kind: 'company', currency: '$' },
  { symbol: 'META', name: 'Meta', market: 'Global', sector: 'Communication', price: 689.12, change: 2.76, size: 5, kind: 'company', currency: '$' },
  { symbol: 'JPM', name: 'JPMorgan', market: 'Global', sector: 'Financials', price: 278.42, change: 0.82, size: 5, kind: 'company', currency: '$' },
  { symbol: 'RELIANCE', name: 'Reliance Industries', market: 'India', sector: 'Energy', price: 1296.4, change: 3.82, size: 8, kind: 'company', currency: '₹' },
  { symbol: 'TCS', name: 'Tata Consultancy', market: 'India', sector: 'Technology', price: 4195.2, change: 2.97, size: 7, kind: 'company', currency: '₹' },
  { symbol: 'HDFCBANK', name: 'HDFC Bank', market: 'India', sector: 'Financials', price: 1724.5, change: 2.61, size: 7, kind: 'company', currency: '₹' },
  { symbol: 'INFY', name: 'Infosys', market: 'India', sector: 'Technology', price: 1541.2, change: 2.48, size: 6, kind: 'company', currency: '₹' },
  { symbol: 'ICICIBANK', name: 'ICICI Bank', market: 'India', sector: 'Financials', price: 1248.75, change: 2.31, size: 6, kind: 'company', currency: '₹' },
  { symbol: 'TATAMOTORS', name: 'Tata Motors', market: 'India', sector: 'Automotive', price: 684.3, change: -1.42, size: 5, kind: 'company', currency: '₹' },
  { symbol: 'SBIN', name: 'State Bank of India', market: 'India', sector: 'Financials', price: 812.6, change: -0.74, size: 5, kind: 'company', currency: '₹' },
  { symbol: 'GOLD', name: 'Gold', market: 'Commodity', sector: 'Precious metals', price: 4215.3, change: 0.92, size: 7, kind: 'commodity', currency: '$' },
  { symbol: 'SILVER', name: 'Silver', market: 'Commodity', sector: 'Precious metals', price: 32.18, change: 1.36, size: 5, kind: 'commodity', currency: '$' },
  { symbol: 'BRENT', name: 'Brent crude', market: 'Commodity', sector: 'Energy', price: 73.84, change: -1.28, size: 6, kind: 'commodity', currency: '$' },
  { symbol: 'NATGAS', name: 'Natural gas', market: 'Commodity', sector: 'Energy', price: 3.12, change: -0.87, size: 4, kind: 'commodity', currency: '$' },
  { symbol: 'COPPER', name: 'Copper', market: 'Commodity', sector: 'Industrial metals', price: 4.31, change: 0.64, size: 4, kind: 'commodity', currency: '$' },
  { symbol: 'WHEAT', name: 'Wheat', market: 'Commodity', sector: 'Agriculture', price: 568.2, change: -0.22, size: 3, kind: 'commodity', currency: '$' },
]

const INDEX_PREVIEW = [
  { name: 'NIFTY 50', value: '26,312.45', change: '+0.68%', flag: '🇮🇳' },
  { name: 'SENSEX', value: '87,418.92', change: '+0.71%', flag: '🇮🇳' },
  { name: 'S&P 500', value: '6,835.32', change: '+0.74%', flag: '🇺🇸' },
  { name: 'NASDAQ', value: '21,702.96', change: '+1.12%', flag: '🇺🇸' },
]

const money = (asset: HeatmapAsset) =>
  `${asset.currency}${asset.price.toLocaleString('en-US', { maximumFractionDigits: 2 })}`

function changeTone(change: number) {
  if (change >= 2) return 'bg-emerald-600/90 text-white border-emerald-400/30'
  if (change > 0) return 'bg-emerald-900/90 text-emerald-50 border-emerald-500/20'
  if (change <= -1) return 'bg-rose-700/90 text-white border-rose-400/30'
  return 'bg-rose-950/90 text-rose-100 border-rose-500/20'
}

function HeatTile({ asset, selected, onClick }: { asset: HeatmapAsset; selected: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`${asset.name} · ${money(asset)} · ${asset.change > 0 ? '+' : ''}${asset.change.toFixed(2)}%`}
      className={cn(
        'group relative flex min-h-24 flex-col justify-between overflow-hidden rounded-lg border p-3 text-left transition-all hover:z-10 hover:scale-[1.02] hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
        changeTone(asset.change),
        selected && 'ring-2 ring-primary ring-offset-2 ring-offset-background'
      )}
      style={{ gridColumn: `span ${asset.size >= 8 ? 2 : 1}` }}
    >
      <span className="text-xs font-semibold opacity-80">{asset.symbol}</span>
      <span>
        <span className="block truncate text-sm font-bold">{asset.name}</span>
        <span className="mt-0.5 block text-lg font-bold tabular-nums">
          {asset.change > 0 ? '+' : ''}{asset.change.toFixed(2)}%
        </span>
      </span>
      <span className="text-[11px] opacity-75">{money(asset)}</span>
    </button>
  )
}

export default function Heatmap() {
  const [market, setMarket] = useState<Market>('all')
  const [period, setPeriod] = useState('1D')
  const [query, setQuery] = useState('')
  const [moverMarket, setMoverMarket] = useState<'India' | 'Global'>('India')
  const [moverSide, setMoverSide] = useState<'gainers' | 'losers'>('gainers')
  const [selectedSymbol, setSelectedSymbol] = useState('AAPL')

  const assets = useMemo(() => PREVIEW_ASSETS.filter((asset) => {
    const marketMatch =
      market === 'all' ||
      (market === 'india' && asset.market === 'India') ||
      (market === 'global' && asset.market === 'Global') ||
      (market === 'commodities' && asset.kind === 'commodity')
    const searchMatch = !query || `${asset.symbol} ${asset.name} ${asset.sector}`.toLowerCase().includes(query.toLowerCase())
    return marketMatch && searchMatch
  }), [market, query])

  const selected = PREVIEW_ASSETS.find((asset) => asset.symbol === selectedSymbol) ?? PREVIEW_ASSETS[0]
  const movers = PREVIEW_ASSETS
    .filter((asset) => asset.market === moverMarket)
    .sort((a, b) => moverSide === 'gainers' ? b.change - a.change : a.change - b.change)
    .slice(0, 5)

  const groups = Array.from(new Set(assets.map((asset) => asset.sector)))
  const marketButtons: { value: Market; label: string }[] = [
    { value: 'all', label: 'All markets' },
    { value: 'india', label: 'India' },
    { value: 'global', label: 'Global' },
    { value: 'commodities', label: 'Commodities' },
  ]

  return (
    <div className="mx-auto max-w-[1800px] space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight">Market Heatmap</h1>
            <Badge variant="outline" className="border-amber-500/40 text-amber-600">Preview data</Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">Global companies, Indian equities and commodities in one interactive market view.</p>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/5 px-3 py-1.5 text-xs text-amber-600">
          <Activity className="h-3.5 w-3.5" />
          Provider connection pending
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
        {INDEX_PREVIEW.map((index) => (
          <Card key={index.name} className="border-border/70 bg-card/80">
            <CardContent className="flex items-center justify-between p-3">
              <div>
                <div className="text-xs text-muted-foreground">{index.flag} {index.name}</div>
                <div className="mt-1 text-lg font-semibold tabular-nums">{index.value}</div>
              </div>
              <div className="text-sm font-semibold text-emerald-500">{index.change}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1 rounded-lg border bg-card p-1">
          {marketButtons.map((button) => (
            <Button key={button.value} size="sm" variant={market === button.value ? 'default' : 'ghost'} onClick={() => setMarket(button.value)}>
              {button.label}
            </Button>
          ))}
        </div>
        <div className="relative min-w-48 flex-1 sm:max-w-xs">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search symbol, company or sector" className="pl-9" />
        </div>
        <div className="ml-auto flex items-center gap-1 rounded-lg border bg-card p-1">
          {['1D', '1W', '1M', '3M', '1Y'].map((value) => (
            <Button key={value} size="sm" variant={period === value ? 'default' : 'ghost'} onClick={() => setPeriod(value)}>{value}</Button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-3">
          {groups.length === 0 ? (
            <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">No instruments match your search.</CardContent></Card>
          ) : groups.map((group) => {
            const groupAssets = assets.filter((asset) => asset.sector === group)
            const average = groupAssets.reduce((sum, asset) => sum + asset.change, 0) / groupAssets.length
            return (
              <Card key={group} className="overflow-hidden border-border/70">
                <CardHeader className="flex flex-row items-center justify-between space-y-0 px-4 py-3">
                  <CardTitle className="text-sm">{group}</CardTitle>
                  <span className={cn('text-xs font-semibold tabular-nums', average >= 0 ? 'text-emerald-500' : 'text-rose-500')}>
                    {average > 0 ? '+' : ''}{average.toFixed(2)}% avg
                  </span>
                </CardHeader>
                <CardContent className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                  {groupAssets.map((asset) => (
                    <HeatTile key={asset.symbol} asset={asset} selected={selectedSymbol === asset.symbol} onClick={() => setSelectedSymbol(asset.symbol)} />
                  ))}
                </CardContent>
              </Card>
            )
          })}
        </div>

        <aside className="space-y-4">
          <Card>
            <CardHeader className="space-y-3 pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-base"><Globe2 className="h-4 w-4" /> Market movers</CardTitle>
                <Badge variant="outline">Top 5</Badge>
              </div>
              <div className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1">
                {(['India', 'Global'] as const).map((value) => (
                  <Button key={value} size="sm" variant={moverMarket === value ? 'default' : 'ghost'} onClick={() => setMoverMarket(value)}>{value}</Button>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-1">
                <Button size="sm" variant={moverSide === 'gainers' ? 'secondary' : 'ghost'} onClick={() => setMoverSide('gainers')}><ArrowUpRight className="mr-1 h-4 w-4 text-emerald-500" /> Gainers</Button>
                <Button size="sm" variant={moverSide === 'losers' ? 'secondary' : 'ghost'} onClick={() => setMoverSide('losers')}><ArrowDownRight className="mr-1 h-4 w-4 text-rose-500" /> Losers</Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-1">
              {movers.map((asset, index) => (
                <button key={asset.symbol} type="button" onClick={() => setSelectedSymbol(asset.symbol)} className="flex w-full items-center justify-between rounded-md px-2 py-2 text-left hover:bg-muted">
                  <span className="flex items-center gap-2"><span className="text-xs text-muted-foreground">{index + 1}</span><span><span className="block text-sm font-semibold">{asset.symbol}</span><span className="block text-xs text-muted-foreground">{asset.name}</span></span></span>
                  <span className={cn('text-sm font-semibold tabular-nums', asset.change >= 0 ? 'text-emerald-500' : 'text-rose-500')}>{asset.change > 0 ? '+' : ''}{asset.change.toFixed(2)}%</span>
                </button>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-base"><SlidersHorizontal className="h-4 w-4" /> Heatmap guide</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-xs text-muted-foreground">
              <p>Tile colour represents percentage change. Tile area is a visual weight placeholder until market-cap and contract-size metadata are connected.</p>
              <div className="flex flex-wrap gap-2"><Badge className="bg-emerald-700">Strong gain</Badge><Badge className="bg-emerald-950">Gain</Badge><Badge className="bg-rose-950">Loss</Badge><Badge className="bg-rose-700">Strong loss</Badge></div>
              <p className="flex items-center gap-2"><CircleDollarSign className="h-4 w-4" /> Preview values are illustrative, not live quotes.</p>
            </CardContent>
          </Card>
        </aside>
      </div>

      <Card className="border-primary/20">
        <CardContent className="grid gap-4 p-4 md:grid-cols-[1fr_2fr_1fr] md:items-center">
          <div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">{selected.market === 'Commodity' ? <Gem className="h-4 w-4" /> : selected.market === 'India' ? '🇮🇳' : <Globe2 className="h-4 w-4" />} {selected.market} · {selected.sector}</div>
            <div className="mt-1 text-xl font-bold">{selected.name} <span className="text-sm text-muted-foreground">{selected.symbol}</span></div>
            <div className="mt-2 text-2xl font-bold tabular-nums">{money(selected)}</div>
            <div className={cn('mt-1 text-sm font-semibold', selected.change >= 0 ? 'text-emerald-500' : 'text-rose-500')}>{selected.change > 0 ? '+' : ''}{selected.change.toFixed(2)}% <span className="font-normal text-muted-foreground">({period} preview)</span></div>
          </div>
          <div className="rounded-lg border bg-muted/30 p-4">
            <div className="mb-3 flex items-center justify-between text-xs text-muted-foreground"><span className="flex items-center gap-2"><BarChart3 className="h-4 w-4" /> Price chart placeholder</span><span>{period}</span></div>
            <div className="flex h-16 items-end gap-1" aria-label="Illustrative chart preview">
              {[24, 32, 28, 43, 38, 51, 46, 58, 52, 68, 61, 76, 70, 84, 78, 92, 86, 72, 80, 88].map((height, index) => <div key={index} className="flex-1 rounded-t-sm bg-primary/70" style={{ height: `${height}%` }} />)}
            </div>
            <p className="mt-2 text-[10px] text-muted-foreground">Chart will be connected to stored OHLCV data.</p>
          </div>
          <div className="space-y-2 text-xs">
            <div className="flex items-center justify-between"><span className="text-muted-foreground">Data status</span><Badge variant="outline" className="border-amber-500/40 text-amber-600">Preview only</Badge></div>
            <div className="flex items-center justify-between"><span className="text-muted-foreground">Market</span><span>{selected.market}</span></div>
            <div className="flex items-center justify-between"><span className="text-muted-foreground">Asset type</span><span>{selected.kind}</span></div>
            <div className="flex items-center justify-between"><span className="text-muted-foreground">Sector / group</span><span>{selected.sector}</span></div>
            <div className="flex items-center justify-between"><span className="text-muted-foreground">Source</span><span>Not connected</span></div>
          </div>
        </CardContent>
      </Card>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span className="flex items-center gap-2"><Layers3 className="h-3.5 w-3.5" /> Unified company + commodity view</span>
        <span className="flex items-center gap-2"><Factory className="h-3.5 w-3.5" /><Fuel className="h-3.5 w-3.5" /><Wheat className="h-3.5 w-3.5" /> Market data integration is the next milestone</span>
      </div>
    </div>
  )
}
