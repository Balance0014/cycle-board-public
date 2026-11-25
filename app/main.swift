import Cocoa

// 菜单栏「看板」图标（应用包仍叫「美国四年周期」）。
// 第一层：更新时间（出问题时换成红 / 橙的问题行）+ 报警和它的结论 + 每个题目一项（「看板」里的每个子文件夹 = 一个题目）；
//   鼠标移上去在旁边展开该题目的图，第一行写这个题目几点更新、最新数据到哪天。
// 图上的格子、表头、时间点：鼠标停上去浮出依据（说明来自图旁边的同名 .json）。
// 置顶项目（状态文件「置顶」，如 XEN 流通进度）画在第一层最上面、和图 N 分开；「看板」根目录下的图（以后的共振总表）紧接其后。
// 每 30 分钟在后台从 GitHub 拉一次最新图，拉完自己检查健康：
//   红：自动更新超过 FAIL_DAYS 天没成功（云端停了、整次验收不过、本机同步不了，最后都表现为「更新」时间变旧）、
//       某个题目连着 FAIL_DAYS 天回到上一版（11-25 加：原来一个题目坏几个星期也只是橙）、第二来源真核了对不上；
//   橙：某个题目这一班回到了上一版（状态文件「出错」：算不出 / 出不了图 / 它自己的验收不过，别的题目照常更新）、
//       某条数据按它自己的公布节奏停太久或这次没下载到（「数据问题」）、有结论变了还没复核；
//       云端某一班没跑成（状态文件「云端失败」，云端失败时自己记的；11-25 加，不用等 2 天变红才知道）、
//       本机超过一天同步不下来（网络或 GitHub 登录过期；红的时候也写明是本机的问题，不误说成云端没更新）；
//   都会加 ⚠︎，不用点开就能看到；点开逐条写明是哪个题目、哪条数据、从哪天起。
//   11-24 前红色看的是「所有题目里最旧的数据日期超过 4 天」：实际利率周五的数下周一才贴出来，周末一过就误报红；
//   一个题目崩了整个看板都不更新。现在按每条数据自己的节奏判断（pipeline/fetch.py MAX_AGE），坏一处只标一处。
//   某个题目的报警信号触发了（比如利率曲线倒挂）：图标变橙、不加 ⚠︎，下拉最上面列出报警和结论；报警解除后下一次同步自动变回。
// 按钮只放一个图标（2026-11-18：菜单栏放不下，图标被刘海挡住；原「美国四年周期」约 100 点宽，
// 改成「看板」两字 48 点仍挤到微信，再改成图标）。TITLE 是图标读不出来时的备用字，也是读屏名
let ICON = "chart.line.uptrend.xyaxis"
let TITLE = "看板"
let FAIL_DAYS = 2           // 「更新」（最后一次成功发布）超过 2 天才报红：云端每天两班，GitHub 定时经常晚几个小时；
                            // 超过 2 天＝至少整整一天两班都没跑成，偶尔一班失败不报
// 置顶项目（XEN 流通进度，2026-11-18：项目放最上面，和周期模型图 N 分开）。云端每天查一次，有自己的断更报警：
//   当天没取到能用的数 → 橙；连续两班都没取到（最近成功已过 PIN_FAIL_DAYS 天）→ 红；
//   网站超过 PIN_SITE_DAYS 天没重算未来释放曲线 → 橙（平时 2–6 天一次；它的卡片每小时刷新，标的「更新时间」只是曲线重算时间）。
let PIN_FAIL_DAYS = 3
let PIN_SITE_DAYS = 7

// ── 悬停浮现（2026-11-18：注释不要密密麻麻写在图上，鼠标停上去再浮出来）──
// 每张图旁边有同名 .json（出图时量好的）：图上每块区域的位置和说明。鼠标进入那块，就在旁边浮出说明框。
final class TipPanel {
    static let shared = TipPanel()
    private let panel: NSPanel
    private let label = NSTextField(wrappingLabelWithString: "")
    private let maxWidth: CGFloat = 300, pad: CGFloat = 10

    private init() {
        panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 10, height: 10),
                        styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.level = NSWindow.Level(rawValue: NSWindow.Level.popUpMenu.rawValue + 1)   // 要压在菜单上面
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.ignoresMouseEvents = true
        panel.collectionBehavior = [.canJoinAllSpaces, .transient, .ignoresCycle]
        let bg = NSView()
        bg.wantsLayer = true
        bg.layer?.backgroundColor = NSColor(white: 0.13, alpha: 0.97).cgColor
        bg.layer?.cornerRadius = 9
        label.font = .systemFont(ofSize: 14)
        label.textColor = .white
        label.isSelectable = false
        bg.addSubview(label)
        panel.contentView = bg
    }

    /// 在 anchor（屏幕坐标）下方浮出；下面放不下就放上面
    func show(_ text: String, below anchor: NSRect) {
        let para = NSMutableParagraphStyle(); para.lineSpacing = 3
        let s = NSAttributedString(string: text, attributes: [.font: NSFont.systemFont(ofSize: 14), .paragraphStyle: para,
                                                              .foregroundColor: NSColor.white])
        let box = s.boundingRect(with: NSSize(width: maxWidth, height: 2000), options: [.usesLineFragmentOrigin, .usesFontLeading])
        let tw = ceil(box.width) + 4, th = ceil(box.height) + 2
        label.attributedStringValue = s
        label.frame = NSRect(x: pad, y: pad, width: tw, height: th)
        let w = tw + 2 * pad, h = th + 2 * pad
        let screen = (NSScreen.screens.first { $0.frame.intersects(anchor) } ?? NSScreen.main)?.visibleFrame ?? anchor
        var x = anchor.minX, y = anchor.minY - 6 - h
        if y < screen.minY + 4 { y = anchor.maxY + 6 }
        x = min(max(x, screen.minX + 4), screen.maxX - w - 4)
        panel.setFrame(NSRect(x: x, y: y, width: w, height: h), display: true)
        panel.orderFrontRegardless()
    }

    func hide() { panel.orderOut(nil) }
}

final class HoverImage: NSView {
    private var tips: [(rect: NSRect, text: String, link: URL?)] = []
    private let ring = CALayer()
    private var current: Int?

    /// tipsURL：出图时量好的说明（单位就是菜单里的点，左上角起算）；没有这个文件就只显示图
    init(image: NSImage, size: NSSize, tipsURL: URL) {
        super.init(frame: NSRect(x: 0, y: 0, width: size.width + 20, height: size.height + 10))
        wantsLayer = true
        let iv = NSImageView(frame: NSRect(x: 10, y: 5, width: size.width, height: size.height))
        iv.image = image
        iv.imageScaling = .scaleProportionallyUpOrDown
        iv.wantsLayer = true
        iv.layer?.cornerRadius = 12
        iv.layer?.masksToBounds = true
        addSubview(iv)
        ring.borderWidth = 2
        ring.cornerRadius = 8
        ring.borderColor = NSColor.systemBlue.withAlphaComponent(0.75).cgColor
        ring.isHidden = true
        ring.zPosition = 10
        layer?.addSublayer(ring)
        guard let data = try? Data(contentsOf: tipsURL),
              let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let list = j["浮现"] as? [[String: Any]] else { return }
        for x in list {
            guard let px = x["x"] as? Double, let py = x["y"] as? Double, let pw = x["w"] as? Double,
                  let ph = x["h"] as? Double, let text = x["字"] as? String else { continue }
            // 网页坐标左上角起算，这里左下角起算；图放在 (10, 5)
            let r = NSRect(x: 10 + px, y: 5 + Double(size.height) - py - ph, width: pw, height: ph)
            let link = (x["链"] as? String).flatMap { URL(string: $0) }   // 出处：点一下打开网页
            tips.append((r, link == nil ? text : text + "\n点一下打开网页", link))
            addTrackingArea(NSTrackingArea(rect: r, options: [.mouseEnteredAndExited, .activeAlways],
                                           owner: self, userInfo: ["i": tips.count - 1]))
        }
    }

    required init?(coder: NSCoder) { fatalError() }

    override func mouseEntered(with e: NSEvent) {
        guard let i = e.trackingArea?.userInfo?["i"] as? Int, i < tips.count, let win = window else { return }
        current = i
        CATransaction.begin(); CATransaction.setDisableActions(true)
        ring.frame = tips[i].rect.insetBy(dx: -1, dy: -1)
        ring.isHidden = false
        CATransaction.commit()
        TipPanel.shared.show(tips[i].text, below: win.convertToScreen(convert(tips[i].rect, to: nil)))
    }

    override func mouseExited(with e: NSEvent) {
        guard let i = e.trackingArea?.userInfo?["i"] as? Int, i == current else { return }   // 相邻两块：先进后出时别把新的关掉
        current = nil
        ring.isHidden = true
        TipPanel.shared.hide()
    }

    // 菜单里的自定义视图收得到松开鼠标；点在出处上就打开网页并收起菜单
    override func mouseUp(with e: NSEvent) {
        let p = convert(e.locationInWindow, from: nil)
        guard let hit = tips.first(where: { $0.link != nil && $0.rect.contains(p) }), let url = hit.link else { return }
        TipPanel.shared.hide()
        enclosingMenuItem?.menu?.cancelTracking()
        NSWorkspace.shared.open(url)
    }

    override func viewDidMoveToWindow() {
        if window == nil { current = nil; ring.isHidden = true; TipPanel.shared.hide() }
    }
}

// 子菜单关掉时（换到别的题目、点了别处、按了退出键）把说明框一起收掉
final class TipCloser: NSObject, NSMenuDelegate {
    func menuDidClose(_ menu: NSMenu) { TipPanel.shared.hide() }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var item: NSStatusItem!
    // 菜单只读这份「只读副本」：它永远和 GitHub 上云端验收通过的版本一模一样（每次同步直接对齐）。
    // 开发在「经济周期看板」里做，本机怎么调试都碰不到菜单显示的东西。
    private let repo = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/经济周期看板-菜单副本")
    private var board: URL { repo.appendingPathComponent("看板") }
    private var lastSync = Date.distantPast
    private var syncNote = "尚未同步"
    private var syncFailed = false
    private var syncProc: Process?
    private let SYNC_OK_KEY = "上次同步成功"   // 记在本机偏好里，程序重开也知道本机多久没同步下来了
    private var timer: Timer?
    private let tipCloser = TipCloser()

    func applicationDidFinishLaunching(_ n: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.autosaveName = "CycleBoard"
        item.isVisible = true
        item.button?.toolTip = "经济周期结论看板"
        let menu = NSMenu()
        menu.delegate = self
        item.menu = menu
        refreshTitle()
        sync(force: true)
        // 每 30 分钟：先按今天的日期重新判断颜色（不等同步结束；11-25 查出同步卡住时图标颜色一直不变），再同步
        timer = Timer.scheduledTimer(withTimeInterval: 1800, repeats: true) { [weak self] _ in
            self?.refreshTitle()
            self?.sync(force: true)
        }
    }

    // ── 健康检查：只看程序写的状态文件和今天的日期，不靠任何外部服务 ──
    // level：0 正常 / 1 要人看（待复核、XEN 没取到数）/ 2 别信（断更、来源对不上）。
    // signals：行情触发的报警（比如比特币跌破 200 周均线），不是程序出错，不加 ⚠︎（2026-11-19 看到「⚠︎ 相关结论可能要变」以为出事了）。
    //   每条带那张图「对现在」的结论，菜单里直接写结论（2026-11-19「结论是啥」）。
    private struct Alarm { let title: String; let text: String }
    private struct Health { let lines: [String]; let level: Int; var signals: [Alarm] = [] }

    private func status() -> [String: Any] {
        guard let data = try? Data(contentsOf: board.appendingPathComponent("状态.json")),
              let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return j
    }

    private func utcDate(_ s: String?) -> Date? {
        guard let s = s else { return nil }
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "UTC")
        return f.date(from: s)
    }

    private func cn(_ d: Date) -> String {
        let m = Calendar(identifier: .gregorian).dateComponents(in: TimeZone(identifier: "UTC")!, from: d)
        return "\(m.month ?? 0)月\(m.day ?? 0)日"
    }

    // 置顶项目各自的健康：note 写在它子菜单第一行，alarm 有内容时也上菜单第一层并让菜单栏变色
    private struct Pin { let dir: String; let note: String; let alarm: String?; let level: Int }

    private func pins() -> [Pin] {
        let items = (status()["置顶"] as? [[String: Any]]) ?? []
        return items.compactMap { p in
            guard let dir = p["目录"] as? String else { return nil }
            let name = dir.components(separatedBy: " ").first ?? dir
            guard let ok = utcDate(p["最近成功"] as? String), let site = utcDate(p["网站截至"] as? String) else {
                return Pin(dir: dir, note: "⚠︎ 读不到 \(name) 的状态", alarm: "⚠︎ 读不到 \(name) 的状态", level: 2)
            }
            let okAge = Int(Date().timeIntervalSince(ok) / 86400), siteAge = Int(Date().timeIntervalSince(site) / 86400)
            let failed = p["失败"] as? String
            let checked = okAge == 0 ? "今天已核" : (okAge == 1 ? "昨天已核" : "\(okAge) 天前已核")
            if okAge >= PIN_FAIL_DAYS {
                let why = failed.map { "（\($0)）" } ?? ""
                let a = "⚠︎ \(name) 已 \(okAge) 天没取到能用的数\(why)，表还是上次的"
                return Pin(dir: dir, note: a, alarm: a, level: 2)
            }
            if let failed = failed {
                let a = "⚠︎ \(name) 这次没取到新数：\(failed)；表还是上次的"
                return Pin(dir: dir, note: a, alarm: a, level: 1)
            }
            if siteAge >= PIN_SITE_DAYS {
                let a = "⚠︎ \(name) 网站已 \(siteAge) 天没重算未来曲线（停在 \(cn(site))）"
                return Pin(dir: dir, note: a, alarm: a, level: 1)
            }
            // 正常时和别的题目同一个写法「11月19日 7:20 更新 · 最新数据 11月16日」（2026-11-19：核对一致这种是给维护的人看的）
            return Pin(dir: dir, note: "\(updatedText(status()) ?? checked) · 最新数据 \(cn(site))", alarm: nil, level: 0)
        }
    }

    // 菜单栏总健康 = 周期看板的健康 + 置顶项目的报警，取最严重的颜色
    private func health() -> Health {
        let b = boardHealth()
        let alarms = pins().filter { $0.level > 0 }
        guard !alarms.isEmpty else { return b }
        let pinLines = alarms.compactMap { $0.alarm } + ["跟维护助手说「XEN 没更新」，会查清是哪一环断了"]
        return Health(lines: b.lines + pinLines, level: max(b.level, alarms.map { $0.level }.max() ?? 0), signals: b.signals)
    }

    private func boardHealth() -> Health {
        guard let data = try? Data(contentsOf: board.appendingPathComponent("状态.json")),
              let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return Health(lines: ["⚠︎ 读不到状态，先别按图操作", "跟维护助手说「看板坏了」"], level: 2)
        }
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm"; f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        let updated = (j["更新"] as? String).flatMap { f.date(from: $0) } ?? .distantPast
        let age = Int(Date().timeIntervalSince(updated) / 86400)
        let crossOK = (j["第二来源核对通过"] as? Bool) ?? false
        let pending = (j["待复核"] as? Int) ?? 0
        var bad: [String] = []
        let local = localSyncProblem()
        if age >= FAIL_DAYS {
            if let l = local {
                bad.append("⚠︎ \(l)，看到的还是 \((updatedText(j) ?? "之前").replacingOccurrences(of: " 更新", with: "")) 的图")
            } else {
                bad.append("⚠︎ 自动更新已 \(age) 天没成功（最后一次：\(updatedText(j) ?? "不详")），图上的数可能过时")
            }
        }
        if !crossOK { bad.append("⚠︎ 两个数据来源对不上，先别按图操作") }
        let alarms = ((j["信号报警"] as? [[String: Any]]) ?? []).compactMap { a -> Alarm? in
            guard let t = a["报警"] as? String else { return nil }
            return Alarm(title: t, text: (a["结论"] as? String) ?? "")
        }
        // 橙：坏一处只标一处，逐条写明（别的题目照常更新）
        var warn: [String] = []
        if let c = j["云端失败"] as? [String: Any] {
            let n = (c["次数"] as? Int) ?? 1, step = (c["环节"] as? String) ?? "不详"
            let when = updatedText(["更新": c["时间"] ?? ""])?.replacingOccurrences(of: " 更新", with: "") ?? "最近"
            warn.append(n > 1 ? "⚠︎ 云端已连着 \(n) 班没跑成（最近 \(when)，卡在：\(step)），图还是上一次的"
                              : "⚠︎ 云端 \(when) 那一班没跑成（卡在：\(step)），图还是上一次的")
        }
        if age < FAIL_DAYS, let l = local { warn.append("⚠︎ \(l)") }
        for x in (j["出错"] as? [[String: Any]]) ?? [] {
            let name = (x["题目"] as? String) ?? "有个题目", why = (x["原因"] as? String) ?? ""
            let since = cnDay(x["起"] as? String), days = daysSince(x["起"] as? String)
            if days >= FAIL_DAYS {
                bad.append("⚠︎ \(name) 已 \(days) 天没更新（\(why)），图还是 \(since) 之前的")
            } else {
                warn.append("⚠︎ \(name) 从 \(since) 起没更新（\(why)），图还是之前的")
            }
        }
        for x in (j["数据问题"] as? [[String: Any]]) ?? [] {
            warn.append("⚠︎ \((x["名"] as? String) ?? "有条数据")：\((x["问题"] as? String) ?? "")")
        }
        if pending > 0 { warn.append("⚠︎ 有 \(pending) 处结论变了还没复核，先别当真") }
        if !bad.isEmpty {
            let more = warn.count > 3 ? Array(warn.prefix(2)) + ["…另有 \(warn.count - 2) 条"] : warn
            let ask = local != nil && age >= FAIL_DAYS ? "跟维护助手说「看板同步不下来」，照维护手册查"
                                                      : "跟维护助手说「看板报红」，照维护手册查"
            return Health(lines: bad + more + [ask], level: 2, signals: alarms)
        }
        if !warn.isEmpty {
            let shown = warn.count > 4 ? Array(warn.prefix(3)) + ["…另有 \(warn.count - 3) 条"] : warn
            let ask = warn.count == 1 && pending > 0 ? "跟维护助手说「复核看板」" : "跟维护助手说「看板有橙色提示」，照维护手册查"
            return Health(lines: [updatedText(j) ?? ""].filter { !$0.isEmpty } + shown + [ask], level: 1, signals: alarms)
        }
        // 一切正常时只写一行更新时间（2026-11-19：「两个来源核对一致 · 结论已认可 · 已同步」这种是给维护的人看的，不是给用户看的）
        return Health(lines: [updatedText(j) ?? "已更新"], level: 0, signals: alarms)
    }

    // 某天（状态文件里的北京日期）到今天过了几天；读不出算 0
    private func daysSince(_ s: String?) -> Int {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        guard let s = s, let d = f.date(from: String(s.prefix(10))) else { return 0 }
        var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        return cal.dateComponents([.day], from: cal.startOfDay(for: d), to: cal.startOfDay(for: Date())).day ?? 0
    }

    // 本机同步不下来超过一天：网络不通，或 GitHub 登录过期（副本靠 gh 的登录拉取）。正常返回 nil
    private func localSyncProblem() -> String? {
        guard syncFailed, let ok = UserDefaults.standard.object(forKey: SYNC_OK_KEY) as? Date else { return nil }
        let h = Int(Date().timeIntervalSince(ok) / 3600)
        guard h >= 24 else { return nil }
        return "本机已 \(h / 24) 天没同步下来（网络不通或 GitHub 登录过期）"
    }

    private func cnDay(_ s: String?) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        guard let s = s, let d = f.date(from: String(s.prefix(10))) else { return "最近" }
        let c = Calendar(identifier: .gregorian).dateComponents(in: TimeZone(identifier: "Asia/Shanghai")!, from: d)
        return "\(c.month ?? 0)月\(c.day ?? 0)日"
    }

    // 「11月19日 7:20 更新」：云端最后一次跑成功的时间（北京时间，状态文件「更新」）
    private func updatedText(_ j: [String: Any]) -> String? {
        guard let s = j["更新"] as? String else { return nil }
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm"; f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        guard let d = f.date(from: s) else { return nil }
        let c = Calendar(identifier: .gregorian).dateComponents(in: TimeZone(identifier: "Asia/Shanghai")!, from: d)
        return "\(c.month ?? 0)月\(c.day ?? 0)日 \(c.hour ?? 0):\(String(format: "%02d", c.minute ?? 0)) 更新"
    }

    // 每个题目子菜单第一行：「11月19日 7:20 更新 · 最新数据 11月18日」（2026-11-19「每个图进去后有没有快照日期」）
    private func topicNote(_ dir: String) -> String? {
        let j = status()
        guard let up = updatedText(j), let raw = (j["最新数据"] as? [String: Any])?[dir] as? String else { return nil }
        return "\(up) · 最新数据 \(utcDate(raw).map(cn) ?? raw)"
    }

    // 长结论按标点折成几行，菜单不被撑得太宽
    private func wrap(_ s: String, width: Int = 28) -> [String] {
        var lines: [String] = [], cur = "", clause = ""
        func flush() {
            if !cur.isEmpty && cur.count + clause.count > width { lines.append(cur); cur = "" }
            cur += clause; clause = ""
        }
        for ch in s {
            clause.append(ch)
            if "；。，".contains(ch) { flush() }
        }
        flush()
        if !cur.isEmpty { lines.append(cur) }
        return lines
    }

    // 菜单栏图标（11-19 改）：这台机器的系统不按 contentTintColor / 文字颜色给图标染色，染橙反而画成深色、
    // 压在深色桌面上看不见（2026-11-19「图标看不见」）。所以：正常时用系统模板图（跟别的图标一样自动黑白）；
    // 要注意时自己把图标画成橙 / 红色（不当模板图，系统原样画），要人看或别信时再并排画一个三角感叹号。
    private func statusImage(_ h: Health) -> NSImage? {
        guard let base = NSImage(systemSymbolName: ICON, accessibilityDescription: TITLE) else { return nil }
        let size = NSImage.SymbolConfiguration(pointSize: 14, weight: .regular)
        if h.level == 0 && h.signals.isEmpty {
            let img = base.withSymbolConfiguration(size) ?? base
            img.isTemplate = true
            return img
        }
        let color: NSColor = h.level == 2 ? .systemRed : .systemOrange
        let paint = NSImage.SymbolConfiguration(paletteColors: [color])
        guard let chart = base.withSymbolConfiguration(paint.applying(size)) else { return nil }
        var parts = [chart]
        if h.level > 0, let warn = NSImage(systemSymbolName: "exclamationmark.triangle.fill", accessibilityDescription: "要注意")?
            .withSymbolConfiguration(paint.applying(NSImage.SymbolConfiguration(pointSize: 11, weight: .bold))) {
            parts.append(warn)
        }
        let gap: CGFloat = 3
        let w = parts.reduce(0) { $0 + $1.size.width } + gap * CGFloat(parts.count - 1)
        let ht = parts.map { $0.size.height }.max() ?? 16
        let out = NSImage(size: NSSize(width: w, height: ht), flipped: false) { _ in
            var x: CGFloat = 0
            for p in parts {
                p.draw(in: NSRect(x: x, y: (ht - p.size.height) / 2, width: p.size.width, height: p.size.height))
                x += p.size.width + gap
            }
            return true
        }
        out.isTemplate = false
        return out
    }

    private func refreshTitle() {
        let h = health()
        guard let b = item.button else { return }
        let img = statusImage(h)
        b.contentTintColor = nil
        b.image = img
        b.setAccessibilityTitle(TITLE)
        if img == nil {
            b.title = h.level > 0 ? "⚠︎ " + TITLE : TITLE
            b.imagePosition = .noImage
        } else {
            b.title = ""
            b.imagePosition = .imageOnly
        }
    }

    // 后台同步：只读副本直接对齐 GitHub 上的最新版（副本没人改，对齐不会丢东西）；拉完重新检查健康
    private func sync(force: Bool = false) {
        guard force || Date().timeIntervalSince(lastSync) > 1800 else { return }
        lastSync = Date()
        if let old = syncProc, old.isRunning { old.terminate() }   // 上一次卡住了：掐掉重来
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/sh")
        // 11-25 补：断电或被掐掉留下的锁文件（5 分钟以上没人用的）先清掉，不然以后每次都同步失败、要人手修；
        // 拉取限速：连续 30 秒平均每秒不到 1KB 算卡住、放弃这次（原来网络半死不活时会一直挂着）
        p.arguments = ["-c", "find .git -maxdepth 4 -name '*.lock' -mmin +5 -delete 2>/dev/null; "
                       + "git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 fetch --quiet origin main "
                       + "&& git reset --quiet --hard origin/main"]
        p.currentDirectoryURL = repo
        p.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "HOME": NSHomeDirectory()]
        p.terminationHandler = { [weak self] proc in
            let f = DateFormatter(); f.dateFormat = "HH:mm"; f.timeZone = TimeZone(identifier: "Asia/Shanghai")   // 菜单里的时间都按北京时间
            let t = f.string(from: Date())
            let ok = proc.terminationStatus == 0
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.syncFailed = !ok
                if ok || UserDefaults.standard.object(forKey: self.SYNC_OK_KEY) == nil {
                    UserDefaults.standard.set(ok ? Date() : Date().addingTimeInterval(-60), forKey: self.SYNC_OK_KEY)
                }
                self.syncNote = ok ? "\(t) 已同步" : "\(t) 同步失败，显示本地版"
                self.refreshTitle()
            }
        }
        syncProc = p
        do { try p.run() } catch {
            syncFailed = true
            syncNote = "同步启动不了，显示本地版"
            refreshTitle()
        }
    }

    private func pngs(in dir: URL) -> [URL] {
        let all = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
        return all.filter { $0.pathExtension.lowercased() == "png" }
            .sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
    }

    private func topics() -> [URL] {
        let all = (try? FileManager.default.contentsOfDirectory(at: board, includingPropertiesForKeys: [.isDirectoryKey])) ?? []
        // 顺序按题目登记表（云端写在状态文件里）；登记表里没有的排在后面
        var order: [String] = []
        if let data = try? Data(contentsOf: board.appendingPathComponent("状态.json")),
           let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            order = (j["题目顺序"] as? [String]) ?? []
        }
        func rank(_ u: URL) -> Int { order.firstIndex(of: u.lastPathComponent) ?? order.count }
        let pinned = Set(pins().map { $0.dir })   // 置顶项目单独画在最上面
        return all.filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
                            && !pinned.contains($0.lastPathComponent) }
            .sorted { rank($0) != rank($1) ? rank($0) < rank($1)
                      : $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
    }

    private func imageItem(_ url: URL) -> NSMenuItem? {
        guard let img = NSImage(contentsOf: url), let rep = img.representations.first else { return nil }
        let w = CGFloat(rep.pixelsWide) / 3, h = CGFloat(rep.pixelsHigh) / 3   // 图按 3 倍像素画
        img.size = NSSize(width: w, height: h)
        let mi = NSMenuItem()
        mi.view = HoverImage(image: img, size: img.size, tipsURL: url.deletingPathExtension().appendingPathExtension("json"))
        return mi
    }

    private func textItem(_ s: String, color: NSColor) -> NSMenuItem {
        let mi = NSMenuItem(title: s, action: nil, keyEquivalent: "")
        mi.attributedTitle = NSAttributedString(string: s, attributes: [.foregroundColor: color, .font: NSFont.menuFont(ofSize: 0)])
        return mi
    }

    // 最近 7 天云端自动更新成功几天：云端每次验收通过都会提交一次（来源登记里的下载时间每天都变），
    // 所以「那天有没有机器人的提交」就是「那天那一班到没到」。只读本机仓库，不靠网页、不用登录。
    private func updateRecord() -> String {
        let p = Process(), pipe = Pipe()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/git")
        p.arguments = ["-C", repo.path, "log", "--author=cycle-board-bot", "--format=%cs"]
        p.standardOutput = pipe
        guard (try? p.run()) != nil else { return "自动更新记录读不到" }
        let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        p.waitUntilExit()
        let days = Set(out.split(separator: "\n").map(String.init))
        guard let first = days.min() else { return "自动更新：还没成功过一次" }
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "UTC")
        let today = f.string(from: Date())
        var ok = 0, expect = 0
        for i in 0..<7 {
            let d = f.string(from: Date().addingTimeInterval(Double(-i) * 86400))
            if d < first || (d == today && !days.contains(d)) { continue }   // 上线前的不算；今天这班还没到点也不算
            expect += 1
            if days.contains(d) { ok += 1 }
        }
        return expect == 0 ? "自动更新：今天刚上线" : "自动更新：最近 \(expect) 天成功 \(ok) 天"
    }

    // 改动记录：读仓库里的「改动记录.md」，最新的在上面
    private func changeLogMenu() -> NSMenu {
        let sub = NSMenu()
        let text = (try? String(contentsOf: repo.appendingPathComponent("改动记录.md"), encoding: .utf8)) ?? ""
        var entries = 0
        for line in text.split(separator: "\n").map(String.init) {
            if line.hasPrefix("## ") {
                entries += 1
                if entries > 12 { break }
                if entries > 1 { sub.addItem(.separator()) }
                let mi = NSMenuItem(title: "", action: nil, keyEquivalent: "")
                mi.attributedTitle = NSAttributedString(string: String(line.dropFirst(3)),
                                                        attributes: [.font: NSFont.boldSystemFont(ofSize: 13)])
                sub.addItem(mi)
            } else if line.hasPrefix("- "), entries > 0 {
                sub.addItem(NSMenuItem(title: "   " + line.dropFirst(2), action: nil, keyEquivalent: ""))
            }
        }
        if sub.items.isEmpty { sub.addItem(NSMenuItem(title: "还没有记录", action: nil, keyEquivalent: "")) }
        return sub
    }

    // 数据清单：每条数据多久公布一次、最新到哪（状态文件的「数据清单」，2026-11-20「更新频次必须披露」）
    private func dataListMenu() -> NSMenu {
        let sub = NSMenu()
        let items = (status()["数据清单"] as? [[String: Any]]) ?? []
        for x in items {
            guard let name = x["名"] as? String, let rel = x["公布"] as? String, let last = x["到"] as? String else { continue }
            let p = last.split(separator: "-").compactMap { Int($0) }
            let upto = p.count == 2 ? "\(p[1])月" : (p.count == 3 ? "\(p[1])月\(p[2])日" : last)
            let mi = NSMenuItem(title: "\(name) · \(rel) · 到 \(upto)", action: nil, keyEquivalent: "")
            mi.isEnabled = false
            sub.addItem(mi)
        }
        if sub.items.isEmpty { sub.addItem(NSMenuItem(title: "还没有数据清单", action: nil, keyEquivalent: "")) }
        return sub
    }

    func menuDidClose(_ menu: NSMenu) { TipPanel.shared.hide() }

    func menuNeedsUpdate(_ menu: NSMenu) {
        sync()
        refreshTitle()
        menu.removeAllItems()
        let h = health()
        let color: NSColor = h.level == 2 ? .systemRed : (h.level == 1 ? .systemOrange : .secondaryLabelColor)
        for line in h.lines { menu.addItem(textItem(line, color: color)) }
        if syncNote.contains("失败") { menu.addItem(textItem("⚠︎ \(syncNote)", color: .systemOrange)) }   // 同步正常不写
        for a in h.signals {   // 报警：橙色一行说什么响了，下面直接写结论
            menu.addItem(textItem("● \(a.title)", color: .systemOrange))
            for line in wrap(a.text) { menu.addItem(textItem("   \(line)", color: .labelColor)) }
        }
        menu.addItem(.separator())
        let pinned = pins()
        for p in pinned {
            let sub = NSMenu()
            sub.delegate = tipCloser
            let tone: NSColor = p.level == 2 ? .systemRed : (p.level == 1 ? .systemOrange : .secondaryLabelColor)
            sub.addItem(textItem(p.note, color: tone))
            for url in pngs(in: board.appendingPathComponent(p.dir)) { if let mi = imageItem(url) { sub.addItem(mi) } }
            let mi = NSMenuItem(title: p.dir, action: nil, keyEquivalent: "")
            if p.level > 0 {
                mi.attributedTitle = NSAttributedString(string: "⚠︎ " + p.dir, attributes: [
                    .foregroundColor: tone, .font: NSFont.menuFont(ofSize: 0)])
            }
            mi.submenu = sub
            menu.addItem(mi)
        }
        if !pinned.isEmpty { menu.addItem(.separator()) }
        for url in pngs(in: board) { if let mi = imageItem(url) { menu.addItem(mi) } }
        for dir in topics() {
            let sub = NSMenu()
            sub.delegate = tipCloser
            if let note = topicNote(dir.lastPathComponent) { sub.addItem(textItem(note, color: .secondaryLabelColor)) }
            for url in pngs(in: dir) { if let mi = imageItem(url) { sub.addItem(mi) } }
            if sub.items.isEmpty { sub.addItem(NSMenuItem(title: "还没有图", action: nil, keyEquivalent: "")) }
            let mi = NSMenuItem(title: dir.lastPathComponent, action: nil, keyEquivalent: "")
            mi.submenu = sub
            menu.addItem(mi)
        }
        menu.addItem(.separator())
        menu.addItem(textItem(updateRecord(), color: .secondaryLabelColor))
        let dataList = NSMenuItem(title: "数据清单（多久更新一次）", action: nil, keyEquivalent: "")
        dataList.submenu = dataListMenu()
        menu.addItem(dataList)
        let changes = NSMenuItem(title: "改动记录（结论和规则每次变了什么）", action: nil, keyEquivalent: "")
        changes.submenu = changeLogMenu()
        menu.addItem(changes)
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "退出看板", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
