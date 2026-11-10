// AI usage panel of the portfolio page: figures, daily activity, months, tools and models.
// index.html loads this file when the visitor gets near the section, so it never holds up the first paint.
// The ai-usage workflow publishes the numbers every 6 hours. The page draws the snapshot written
// into it first, then swaps in the live file when it arrives; if it never does, the snapshot stays.
// Everything read from the file is written with textContent, never as markup.
// If anything here fails, the figures written in the page simply stay as they are.
(function () {
    'use strict';
    try {
        init();
    } catch (err) {
        console.error(err);
    }

    function init() {
        const card = document.getElementById('usageCard');
        if (!card) return;
        const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        const SOURCES = [
            'https://raw.githubusercontent.com/LucasYanzy/Lucasyanzy/usage/ai-usage.json',
            'https://cdn.jsdelivr.net/gh/LucasYanzy/Lucasyanzy@usage/ai-usage.json'   // a mirror, for networks that cannot reach the first
        ];
        // One fixed colour per tool (the README card uses the same map), so a tool keeps its colour
        // whatever its rank. The hues are a set checked for colour-blind separation on a dark surface.
        const TOOL_COLORS = { codex: '#3987e5', claude: '#d95926', gemini: '#199e70', cursor: '#c98500', copilot: '#d55181', opencode: '#008300', kimi: '#9085e9', deepseek: '#e66767' };
        const OTHER = '#6b7690';
        // marks in assets/provider-icons; 'mono' ones are a single colour and are shown in white
        const ICONS = { claude: '', codex: '', copilot: '', deepseek: '', gemini: '', kimi: '', cursor: 'mono', opencode: 'mono' };
        const DAY = 86400000;
        const own = (map, key) => Object.prototype.hasOwnProperty.call(map, key);
        const $ = (sel) => card.querySelector(sel);
        const grid = $('#usageGrid'), heatBox = $('.usage-heat'), cols = $('#usageCols');
        const tip = $('#usageTip'), live = $('#usageLive');
        let raw = null, days = [], start = 0, shownFrom = 0, weeks = 0, colCount = 0, months = [], shownMonths = [];
        let cursor = -1, marked = null, pinned = false, lastPointer = 'mouse', playing = false, queued = null;

        const make = (tag, cls, text) => {
            const e = document.createElement(tag);
            if (cls) e.className = cls;
            if (text != null) e.textContent = text;
            return e;
        };
        // three significant figures with a unit: 1309185720 -> 1.31B
        const short = (n) => {
            const units = [[1e12, 'T'], [1e9, 'B'], [1e6, 'M'], [1e3, 'K']];
            for (let u = 0; u < units.length; u++) {
                if (n >= units[u][0]) {
                    const v = n / units[u][0];
                    return (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2)) + units[u][1];
                }
            }
            return String(Math.round(n));
        };
        const share = (v) => (v < 0.1 ? '<0.1%' : (Math.round(v * 10) / 10) + '%');
        const dateOf = (i) => new Date(start + i * DAY);
        // dates are UTC days, written the same way everywhere: 13 Jul 2026
        const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const mon = (date) => MONTHS[date.getUTCMonth()];
        const monYear = (date) => mon(date) + ' ' + date.getUTCFullYear();
        const dmy = (date) => date.getUTCDate() + ' ' + monYear(date);
        const set = (key, value) => card.querySelectorAll('[data-usage="' + key + '"]').forEach((e) => { e.textContent = value; });
        const showIf = (key, on) => card.querySelectorAll('[data-usage-if="' + key + '"]').forEach((e) => { e.hidden = !on; });

        // the file as the page uses it, or null when it is not one
        function read(d) {
            if (!d || typeof d.tokens !== 'string' || typeof d.cost !== 'string' || typeof d.rank !== 'string') return null;
            const out = { raw: d, days: [], start: 0 };
            const daily = d.daily;
            if (daily && Array.isArray(daily.tokens) && /^\d{4}-\d\d-\d\d$/.test(daily.start)) {
                const t = Date.parse(daily.start + 'T00:00:00Z');
                if (isFinite(t)) {
                    out.start = t;
                    out.days = daily.tokens.slice(-371).map((v) => (typeof v === 'number' && isFinite(v) && v > 0 ? v : 0));
                    out.start += (daily.tokens.length - out.days.length) * DAY;
                }
            }
            return out;
        }

        function figures() {
            set('tokens', raw.tokens);
            set('cost', raw.cost);
            set('rank', raw.rank);
            ['tokens_month', 'cost_month'].forEach((key) => {
                const ok = typeof raw[key] === 'string' && raw[key] !== '';
                showIf(key, ok);
                if (ok) set(key, raw[key]);
            });
            const when = new Date(raw.updated);
            if (!isNaN(when)) set('updated', dmy(when));

            // everything about the days is read off the same days the grid shows
            const n = days.length;
            const first = days.findIndex((v) => v > 0);
            showIf('active_days', first >= 0);
            showIf('streak', first >= 0);
            $('.usage-facts').hidden = first < 0;
            if (first >= 0) {
                let active = 0, longest = 0, run = 0, best = first;
                days.forEach((v, i) => {
                    if (v > 0) {
                        active++;
                        run++;
                        if (run > longest) longest = run;
                        if (v > days[best]) best = i;
                    } else run = 0;
                });
                // a day that has only just begun does not break the streak
                let i = n - 1, current = 0;
                if (days[i] <= 0) i--;
                while (i >= 0 && days[i] > 0) { current++; i--; }
                const sum = (from) => days.slice(from).reduce((a, b) => a + b, 0);
                set('active_days', active);
                set('since', first > 0 ? 'of ' + (n - first) + ' since ' + dmy(dateOf(first)) : 'of the last ' + n + ' days');
                set('streak', current);
                set('longest', longest);
                set('best_tokens', short(days[best]));
                set('best_date', '· ' + dmy(dateOf(best)));
                set('average', short(sum(0) / active));
                set('last7', short(sum(-7)));
                set('last30', short(sum(-30)));
            }
            const count = raw.models_count;
            const counted = typeof count === 'number' && count > 0;
            showIf('models_count', counted);
            if (counted) set('models_count', count);
        }

        // One cell per day, weeks left to right, Monday at the top. The grid starts in the week of the
        // first active day, so a profile a few months old is not drawn as a year of empty cells. Where
        // it has a row to itself it shows more weeks, as far as it takes to fill the width; where the
        // screen is too narrow for them it shows fewer.
        function heat(force) {
            const band = $('.usage-activity');
            const n = days.length;
            const first = days.findIndex((v) => v > 0);
            band.hidden = first < 0;
            if (first < 0) return;
            const gap = parseFloat(getComputedStyle(grid).columnGap) || 3;
            const lastRow = (dateOf(n - 1).getUTCDay() + 6) % 7;
            const want = Math.max(16, Math.max(0, Math.ceil((n - first - lastRow - 1) / 7)) + 1);
            // beside the months: as wide as those weeks need at full size; the months take the rest
            band.style.setProperty('--heat', Math.ceil(want * (18 + gap) - gap + heatBox.clientWidth - grid.clientWidth) + 'px');
            const width = grid.clientWidth || 600;
            const fit = Math.floor((width + gap) / (10 + gap));        // cells no smaller than 10px
            const fill = Math.ceil((width + gap) / (18 + gap));        // and no larger than 18px
            const w = Math.max(4, Math.min(53, fit, Math.max(want, fill)));
            if (w === weeks && !force) return;
            weeks = w;
            const from = n - ((w - 1) * 7 + lastRow + 1);              // Monday of the first column; may lie before the data
            shownFrom = Math.max(from, 0);
            if (cursor < shownFrom) cursor = -1;

            const used = days.filter((v) => v > 0).sort((a, b) => a - b);
            const cuts = [0.25, 0.5, 0.75].map((q) => used[Math.min(used.length - 1, Math.floor(used.length * q))]);
            const level = (v) => (v <= 0 ? 0 : 1 + cuts.filter((c) => v > c).length);

            const cells = document.createDocumentFragment();
            const names = document.createDocumentFragment();
            let lastName = -9;
            for (let i = shownFrom; i < n; i++) {
                const k = i - from, col = Math.floor(k / 7);
                const cell = document.createElement('i');
                cell.dataset.i = i;
                cell.dataset.l = level(days[i]);
                cell.style.setProperty('--w', col);
                if (i === shownFrom) {
                    cell.style.gridColumnStart = col + 1;
                    cell.style.gridRowStart = (k % 7) + 1;
                }
                cells.appendChild(cell);
                const date = dateOf(i);
                if (date.getUTCDate() === 1 && col - lastName >= 3 && col <= w - 2) {
                    const name = make('span', '', mon(date));
                    name.style.gridColumnStart = col + 1;
                    names.appendChild(name);
                    lastName = col;
                }
            }
            heatBox.style.setProperty('--weeks', w);
            grid.textContent = '';
            grid.appendChild(cells);
            const head = $('.usage-months');
            head.textContent = '';
            head.appendChild(names);
            $('#usageSpan').textContent = w >= 52 ? 'last 12 months · 近一年' : 'last ' + w + ' weeks · 近 ' + w + ' 周';
            const active = days.slice(shownFrom).filter((v) => v > 0).length;
            grid.setAttribute('aria-label', 'Daily AI token usage over the last ' + w + ' weeks: active on ' + active + ' of ' + (n - shownFrom) +
                ' days. Arrow keys read single days. A table of monthly totals follows.');
        }

        // tokens per month, from the first active month on; as many of the latest as fit
        function byMonth(force) {
            const first = days.findIndex((v) => v > 0);
            months = [];
            if (first < 0) return;
            days.forEach((v, i) => {
                if (i < first) return;
                const date = dateOf(i);
                const key = date.getUTCFullYear() * 12 + date.getUTCMonth();
                let m = months[months.length - 1];
                if (!m || m.key !== key) {
                    m = { key: key, date: date, tokens: 0, active: 0 };
                    months.push(m);
                }
                m.tokens += v;
                if (v > 0) m.active++;
            });
            const room = Math.max(3, Math.min(12, Math.floor((cols.clientWidth || 300) / 38)));
            if (room === colCount && !force) return;
            colCount = room;
            shownMonths = months.slice(-room);
            const top = Math.max.apply(null, shownMonths.map((m) => m.tokens)) || 1;
            const bars = document.createDocumentFragment();
            const names = document.createDocumentFragment();
            shownMonths.forEach((m, i) => {
                const col = make('div', 'usage-col' + (i === shownMonths.length - 1 ? ' now' : ''));
                col.dataset.m = i;
                col.appendChild(make('span', '', short(m.tokens)));
                col.style.setProperty('--i', i);
                const bar = make('i');
                bar.style.setProperty('--h', (m.tokens / top).toFixed(4));
                col.appendChild(bar);
                bars.appendChild(col);
                names.appendChild(make('div', 'usage-colname', mon(m.date)));
            });
            cols.style.setProperty('--n', shownMonths.length);
            cols.textContent = '';
            cols.appendChild(bars);
            cols.appendChild(names);
            cols.setAttribute('aria-label', 'Tokens per month: ' + shownMonths.map((m) => mon(m.date) + ' ' + short(m.tokens)).join(', ') +
                '. The last month is still running.');
            $('#usageMonthNote').textContent = mon(shownMonths[shownMonths.length - 1].date) + ' to date · 本月至今';

            // the same months as a table, for screen readers
            const box = $('#usageTable');
            const table = make('table');
            table.appendChild(make('caption', '', 'AI token usage per month'));
            const head = table.insertRow();
            ['Month', 'Tokens', 'Active days'].forEach((h) => head.appendChild(make('th', '', h)));
            months.forEach((m) => {
                const row = table.insertRow();
                [monYear(m.date), short(m.tokens), m.active].forEach((v) => row.appendChild(make('td', '', v)));
            });
            box.textContent = '';
            box.appendChild(table);
        }

        const rowsOf = (list, max) => (Array.isArray(list) ? list : [])
            .filter((r) => r && typeof r.name === 'string' && r.name && typeof r.pct === 'number' && r.pct > 0)
            .slice(0, max);

        // whose tokens they were: one thin bar split by tool, and the figures in the list under it
        function tools() {
            const box = $('#usageTools');
            const rows = rowsOf(raw.providers, 6);
            box.hidden = !rows.length;
            if (!rows.length) return [];
            const seg = box.querySelector('.usage-seg'), list = box.querySelector('.usage-rows');
            seg.textContent = '';
            list.textContent = '';
            rows.forEach((p, i) => {
                const key = String(p.key || '').toLowerCase();
                const colour = own(TOOL_COLORS, key) ? TOOL_COLORS[key] : OTHER;
                const part = make('i');
                part.dataset.t = i;
                part.style.flex = p.pct + ' 0 0';
                part.style.setProperty('--c', colour);
                seg.appendChild(part);

                const name = make('span', 'usage-name');
                const swatch = make('i');
                swatch.style.setProperty('--c', colour);
                name.appendChild(swatch);
                if (own(ICONS, key)) {
                    const img = new Image(18, 18);
                    img.alt = '';
                    img.loading = 'lazy';
                    if (ICONS[key]) img.className = ICONS[key];
                    img.src = 'assets/provider-icons/' + key + '.svg';
                    name.appendChild(img);
                }
                name.appendChild(make('span', '', p.name));
                const row = make('li');
                row.appendChild(name);
                row.appendChild(make('span', 'usage-amt', typeof p.tokens === 'number' && p.tokens > 0 ? short(p.tokens) : ''));
                row.appendChild(make('span', 'usage-pct', share(p.pct)));
                list.appendChild(row);
            });
            seg.setAttribute('aria-label', 'Share of tokens by tool: ' + rows.map((p) => p.name + ' ' + share(p.pct)).join(', '));
            return rows;
        }

        // the most used models: ranked bars on one baseline, one hue
        function models(beside) {
            const box = $('#usageModels');
            const rows = rowsOf(raw.models, beside ? Math.max(3, Math.min(5, beside + 1)) : 5);   // about as tall as the tools beside them
            box.hidden = !rows.length;
            if (!rows.length) return rows;
            const list = box.querySelector('.usage-rows');
            list.textContent = '';
            const top = Math.max.apply(null, rows.map((m) => m.pct));
            rows.forEach((m, i) => {
                const name = make('span', 'usage-name');
                const text = make('span', '', m.name);
                text.title = m.name;
                name.appendChild(text);
                const bar = make('span', 'usage-bar');
                const fill = make('i');
                fill.style.width = (m.pct / top * 100).toFixed(2) + '%';
                fill.style.setProperty('--i', i);
                bar.appendChild(fill);
                const row = make('li');
                row.appendChild(name);
                row.appendChild(bar);
                row.appendChild(make('span', 'usage-amt', typeof m.tokens === 'number' && m.tokens > 0 ? short(m.tokens) : ''));
                row.appendChild(make('span', 'usage-pct', share(m.pct)));
                list.appendChild(row);
            });
            const count = raw.models_count;
            box.querySelector('.usage-head-note').textContent = (typeof count === 'number' && count > rows.length ? 'top ' + rows.length + ' of ' + count + ', ' : '') +
                'share of tokens, last 12 months · 近一年';
            return rows;
        }

        let toolRows = [];
        function draw(next) {
            if (playing) {                 // not in the middle of the entrance: it would start over
                queued = next;
                return;
            }
            raw = next.raw;
            days = next.days;
            start = next.start;
            hideTip();
            figures();
            heat(true);
            byMonth(true);
            toolRows = tools();
            const modelRows = models(toolRows.length);
            const split = $('.usage-split');
            split.hidden = !toolRows.length && !modelRows.length;
            split.classList.toggle('solo', !toolRows.length !== !modelRows.length);
        }

        // --- one tooltip for every mark: value first, what it is second
        function describe(target) {
            if (!target || !target.closest) return null;
            const cell = target.closest('.usage-grid i');
            if (cell) return dayText(+cell.dataset.i, cell);
            const col = target.closest('.usage-col');
            const m = col && shownMonths[+col.dataset.m];
            if (m) return { el: col, value: short(m.tokens) + ' tokens', what: monYear(m.date) + ' · ' + m.active + ' active days' };
            const part = target.closest('.usage-seg i');
            const p = part && toolRows[+part.dataset.t];
            if (p) return { el: part, value: share(p.pct) + (typeof p.tokens === 'number' && p.tokens > 0 ? ' · ' + short(p.tokens) + ' tokens' : ''), what: p.name };
            return null;
        }
        function dayText(i, cell) {
            if (!(i >= 0 && i < days.length)) return null;
            return {
                el: cell || grid.querySelector('[data-i="' + i + '"]'),
                value: days[i] > 0 ? short(days[i]) + ' tokens' : 'No usage',
                what: WEEKDAYS[dateOf(i).getUTCDay()] + ', ' + dmy(dateOf(i))
            };
        }
        function showTip(d) {
            if (!d || !d.el) return;
            if (marked && marked !== d.el) marked.classList.remove('on');
            marked = d.el;
            marked.classList.add('on');
            tip.textContent = '';
            tip.appendChild(make('b', '', d.value));
            tip.appendChild(document.createTextNode(d.what));
            const box = card.getBoundingClientRect(), r = d.el.getBoundingClientRect();
            const tw = tip.offsetWidth, th = tip.offsetHeight;
            const x = Math.max(8, Math.min(box.width - tw - 8, r.left + r.width / 2 - box.left - tw / 2));
            let y = r.top - box.top - th - 8;
            if (y < 8) y = r.bottom - box.top + 8;
            tip.style.transform = 'translate(' + Math.round(x) + 'px, ' + Math.round(y) + 'px)';
            tip.classList.add('show');
        }
        function hideTip() {
            if (marked) marked.classList.remove('on');
            marked = null;
            pinned = false;
            tip.classList.remove('show');
        }
        card.addEventListener('pointerdown', (e) => { lastPointer = e.pointerType || 'mouse'; }, { passive: true });
        card.addEventListener('pointerover', (e) => {
            if (e.pointerType === 'touch') return;
            const d = describe(e.target);
            if (d) {
                pinned = false;
                showTip(d);
            } else if (!pinned && !(e.target.closest && e.target.closest('.usage-grid, .usage-cols, .usage-seg'))) {
                hideTip();            // between two marks of one chart the last one stays
            }
        });
        card.addEventListener('pointerleave', () => { if (!pinned) hideTip(); });
        // a finger has no hover: a tap shows the mark's text until the next tap elsewhere
        card.addEventListener('click', (e) => {
            if (lastPointer !== 'touch') return;
            const d = describe(e.target);
            if (d) {
                showTip(d);
                pinned = true;
            } else hideTip();
        });
        document.addEventListener('pointerdown', (e) => { if (pinned && !card.contains(e.target)) hideTip(); }, { passive: true });

        // the days can be read from the keyboard: arrows move by a day or a week
        const STEP = { ArrowLeft: -7, ArrowRight: 7, ArrowUp: -1, ArrowDown: 1, Home: -1e5, End: 1e5 };
        function readDay(i) {
            cursor = Math.max(shownFrom, Math.min(days.length - 1, i));
            const d = dayText(cursor);
            if (!d) return;
            showTip(d);
            live.textContent = d.what + ': ' + d.value;
        }
        grid.addEventListener('keydown', (e) => {
            if (!own(STEP, e.key) || !days.length) return;
            e.preventDefault();
            readDay((cursor < 0 ? days.length - 1 : cursor) + STEP[e.key]);
        });
        grid.addEventListener('focus', () => {
            let byKeyboard = true;
            try { byKeyboard = grid.matches(':focus-visible'); } catch (err) { /* older browsers: treat every focus alike */ }
            if (days.length && byKeyboard) readDay(cursor < 0 ? days.length - 1 : cursor);
        });
        grid.addEventListener('blur', hideTip);

        // --- data: the snapshot first
        let snapshot = null;
        try {
            snapshot = JSON.parse(document.getElementById('usageSnapshot').textContent);
        } catch (err) { /* the figures written in the page stay */ }
        const base = read(snapshot);
        if (base) draw(base);

        // how many weeks and months fit depends on the width
        if ('ResizeObserver' in window) {
            let pending = false;
            new ResizeObserver(() => {
                if (pending || !raw) return;
                pending = true;
                requestAnimationFrame(() => {
                    pending = false;
                    hideTip();
                    heat(false);
                    byMonth(false);
                });
            }).observe(heatBox);
        }

        // --- drawn in once, the first time the panel is seen
        if (!reduceMotion && 'IntersectionObserver' in window) {
            const seen = new IntersectionObserver((entries) => {
                if (!entries.some((e) => e.isIntersecting)) return;
                seen.disconnect();
                playing = true;
                card.classList.add('play');
                setTimeout(() => {
                    card.classList.remove('play');
                    playing = false;
                    if (queued) {
                        const next = queued;
                        queued = null;
                        draw(next);
                    }
                }, 2200);
            }, { threshold: 0.12 });
            seen.observe(card);
        }

        // --- the live file. (This script is itself only loaded once the section is getting close.) A part the
        // live file lacks (the profile half is optional) keeps the snapshot's.
        const get = (url) => {
            const stop = 'AbortController' in window ? new AbortController() : null;
            const timer = setTimeout(() => { if (stop) stop.abort(); }, 8000);
            return fetch(url, { cache: 'no-cache', signal: stop ? stop.signal : undefined })
                .then((r) => (r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status))))
                .then((d) => { clearTimeout(timer); return d; }, (err) => { clearTimeout(timer); throw err; });
        };
        SOURCES.reduce((tried, url) => tried.catch(() => get(url)), Promise.reject(new Error('none')))
            .then((d) => {
                if (!d || typeof d !== 'object') return;
                const was = snapshot ? Date.parse(snapshot.updated) : NaN, now = Date.parse(d.updated);
                if (isFinite(was) && isFinite(now) && now < was) return;        // never step back in time
                const next = read(Object.assign({}, snapshot || {}, d));
                if (next) draw(next);
            })
            .catch(() => { /* the snapshot stays */ });
    }
})();
