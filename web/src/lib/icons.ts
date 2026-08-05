import {
  AlertTriangle,
  BarChart3,
  Bell,
  BetweenHorizontalStart,
  Bookmark,
  Bug,
  Calendar,
  ChartLine,
  CheckSquare,
  Clock,
  Code,
  Database,
  FileCode,
  FilePlus,
  FileText,
  Filter,
  Flag,
  FolderTree,
  Gauge,
  Gem,
  Image,
  Info,
  Layers,
  Link,
  List,
  ListChecks,
  ListOrdered,
  ListTree,
  Lock,
  Map,
  MessageSquare,
  Paperclip,
  Puzzle,
  Quote,
  Rocket,
  Search,
  Shapes,
  Sparkles,
  SquareCheckBig,
  Star,
  Table,
  Tags,
  Target,
  Timer,
  TrendingUp,
  Users,
  Workflow,
  Zap,
  type LucideIcon,
} from "lucide-react";

/**
 * Lucide icons a SERVER-declared `icon` name can resolve to (RADD-748).
 *
 * A registry rather than a dynamic import, and the reason is measured rather
 * than assumed. `lucide-react/dynamic` resolves any of ~1500 icons by name, and
 * using it took the production build from **127 chunks / 5.6 MB to 1876 chunks /
 * 13 MB** — Vite emits a chunk per lazy icon. A 15× chunk explosion and 2.3× the
 * assets, to put a 14px glyph beside seven menu entries, is not a trade worth
 * making.
 *
 * So the set is curated and the fallback is honest: a name nobody here knows
 * renders the neutral placeholder rather than nothing at all, which is a visible
 * "this icon is not shipped" instead of a silently missing glyph. Adding one is
 * a single line, and that is deliberately the cost — the alternative is paying
 * 7 MB for icons nobody has asked for.
 *
 * It is shared on purpose. `ValueChip` had its own six-entry copy for issue
 * types, so an issue type and a page extension declaring the same icon name
 * would agree only by coincidence.
 */
const ICONS: Record<string, LucideIcon> = {
  // Issue types (seeded by the backend).
  "square-check-big": SquareCheckBig,
  bug: Bug,
  bookmark: Bookmark,
  sparkles: Sparkles,
  gem: Gem,
  shapes: Shapes,
  // Page extensions (server/src/radd/modules/pages/extensions.py).
  "list-tree": ListTree,
  "folder-tree": FolderTree,
  info: Info,
  link: Link,
  "between-horizontal-start": BetweenHorizontalStart,
  tags: Tags,
  "file-plus": FilePlus,
  // General purpose, for anything a plugin declares.
  "alert-triangle": AlertTriangle,
  "bar-chart-3": BarChart3,
  bell: Bell,
  calendar: Calendar,
  "chart-line": ChartLine,
  "check-square": CheckSquare,
  clock: Clock,
  code: Code,
  database: Database,
  "file-code": FileCode,
  "file-text": FileText,
  filter: Filter,
  flag: Flag,
  gauge: Gauge,
  image: Image,
  layers: Layers,
  list: List,
  "list-checks": ListChecks,
  "list-ordered": ListOrdered,
  lock: Lock,
  map: Map,
  "message-square": MessageSquare,
  paperclip: Paperclip,
  puzzle: Puzzle,
  quote: Quote,
  rocket: Rocket,
  search: Search,
  star: Star,
  table: Table,
  target: Target,
  timer: Timer,
  "trending-up": TrendingUp,
  users: Users,
  workflow: Workflow,
  zap: Zap,
};

/** What an unrecognised name renders as — visibly a placeholder, not a gap. */
export const FALLBACK_ICON = Puzzle;

/** The component for a server-declared icon name, or undefined. */
export const iconFor = (name: string | null | undefined): LucideIcon | undefined =>
  name ? ICONS[name] : undefined;

/** The component for a name, falling back to the placeholder. */
export const iconOrFallback = (name: string | null | undefined): LucideIcon =>
  iconFor(name) ?? FALLBACK_ICON;
