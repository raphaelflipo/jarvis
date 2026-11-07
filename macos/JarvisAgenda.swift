// jarvis-agenda — petit outil local (EventKit) pour le Calendrier et les Rappels du Mac.
// Placé dans Jarvis.app/Contents/MacOS : macOS demande l'accès au nom de « Jarvis », une seule fois.
// Les répétitions (cours chaque semaine…) sont bien prises en compte, contrairement à AppleScript.
// Sortie : JSON sur stdout. Aucune donnée ne quitte le Mac.
import EventKit
import Foundation

let store = EKEventStore()
let iso = ISO8601DateFormatter()
iso.formatOptions = [.withInternetDateTime]
let local = DateFormatter()
local.locale = Locale(identifier: "fr_FR")
local.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"

func out(_ obj: Any) {
    let data = (try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys])) ?? Data("{}".utf8)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

func fail(_ msg: String, _ code: Int32 = 1) -> Never {
    out(["error": msg])
    exit(code)
}

func parse(_ s: String) -> Date? {
    if let d = iso.date(from: s) { return d }
    for f in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm", "yyyy-MM-dd HH:mm", "yyyy-MM-dd"] {
        local.dateFormat = f
        if let d = local.date(from: s) { return d }
    }
    return nil
}

func fmt(_ d: Date?) -> String {
    guard let d = d else { return "" }
    local.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
    return local.string(from: d)
}

func access(_ type: EKEntityType) {
    let st = EKEventStore.authorizationStatus(for: type)
    if st == .denied || st == .restricted {
        fail(type == .event ? "Pas d'accès au Calendrier. Dans Jarvis : Réglages › Général › Calendrier et Rappels › « Autoriser »."
                            : "Pas d'accès aux Rappels. Dans Jarvis : Réglages › Général › Calendrier et Rappels › « Autoriser ».", 3)
    }
    let sem = DispatchSemaphore(value: 0)
    var ok = false
    if #available(macOS 14.0, *) {
        let done: (Bool, Error?) -> Void = { g, _ in ok = g; sem.signal() }
        if type == .event { store.requestFullAccessToEvents(completion: done) } else { store.requestFullAccessToReminders(completion: done) }
    } else {
        store.requestAccess(to: type) { g, _ in ok = g; sem.signal() }
    }
    _ = sem.wait(timeout: .now() + 60)
    if !ok {
        fail(type == .event
             ? "Pas d'accès au Calendrier. Dans Jarvis : Réglages › Général › Calendrier et Rappels › « Autoriser » (ou Réglages Système › Confidentialité et sécurité › Calendriers › Jarvis)."
             : "Pas d'accès aux Rappels. Dans Jarvis : Réglages › Général › Calendrier et Rappels › « Autoriser » (ou Réglages Système › Confidentialité et sécurité › Rappels › Jarvis).", 3)
    }
}

let args = Array(CommandLine.arguments.dropFirst())
guard let cmd = args.first else { fail("commande attendue : events | add-event | reminders | add-reminder | calendars") }

func statusName(_ t: EKEntityType) -> String {
    switch EKEventStore.authorizationStatus(for: t) {
    case .notDetermined: return "pas_demande"
    case .denied, .restricted: return "refuse"
    case .writeOnly: return "ecriture_seule"
    default: return "autorise"
    }
}

switch cmd {
case "status":
    out(["calendar": statusName(.event), "reminders": statusName(.reminder)])

case "calendars":
    access(.event)
    out(store.calendars(for: .event).map { ["title": $0.title, "writable": $0.allowsContentModifications, "source": $0.source.title] })

case "events":
    access(.event)
    guard args.count >= 3, let a = parse(args[1]), let b = parse(args[2]) else { fail("events <début> <fin>") }
    let pred = store.predicateForEvents(withStart: a, end: b, calendars: nil)
    let evs = store.events(matching: pred).sorted { $0.startDate < $1.startDate }.prefix(300)
    out(evs.map { e in
        ["title": e.title ?? "", "start": fmt(e.startDate), "end": fmt(e.endDate), "all_day": e.isAllDay,
         "calendar": e.calendar.title, "location": e.location ?? "", "recurring": e.hasRecurrenceRules] as [String: Any]
    })

case "add-event":
    access(.event)
    guard args.count >= 3, let start = parse(args[2]) else { fail("add-event <titre> <début> [fin] [calendrier] [lieu] [notes]") }
    let e = EKEvent(eventStore: store)
    e.title = args[1]
    e.startDate = start
    let allDay = args[2].count == 10
    e.isAllDay = allDay
    e.endDate = (args.count > 3 && !args[3].isEmpty ? parse(args[3]) : nil) ?? start.addingTimeInterval(allDay ? 86400 : 3600)
    if args.count > 4, !args[4].isEmpty {
        guard let cal = store.calendars(for: .event).first(where: { $0.title.lowercased() == args[4].lowercased() && $0.allowsContentModifications })
        else { fail("Calendrier « \(args[4]) » introuvable ou en lecture seule.") }
        e.calendar = cal
    } else {
        guard let cal = store.defaultCalendarForNewEvents else { fail("Aucun calendrier par défaut.") }
        e.calendar = cal
    }
    if args.count > 5, !args[5].isEmpty { e.location = args[5] }
    if args.count > 6, !args[6].isEmpty { e.notes = args[6] }
    do { try store.save(e, span: .thisEvent) } catch { fail("Enregistrement impossible : \(error.localizedDescription)") }
    out(["ok": true, "title": e.title ?? "", "start": fmt(e.startDate), "end": fmt(e.endDate), "calendar": e.calendar.title])

case "reminders":
    access(.reminder)
    let all = args.count > 1 && args[1] == "all"
    let pred = all ? store.predicateForReminders(in: nil)
                   : store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: nil)
    let sem = DispatchSemaphore(value: 0)
    var items: [[String: Any]] = []
    store.fetchReminders(matching: pred) { rs in
        for r in (rs ?? []).prefix(300) {
            let due = r.dueDateComponents.flatMap { Calendar.current.date(from: $0) }
            items.append(["title": r.title ?? "", "due": fmt(due), "list": r.calendar.title, "done": r.isCompleted,
                          "priority": r.priority])
        }
        sem.signal()
    }
    _ = sem.wait(timeout: .now() + 60)
    out(items.sorted { ($0["due"] as? String ?? "~") < ($1["due"] as? String ?? "~") })

case "add-reminder":
    access(.reminder)
    guard args.count >= 2 else { fail("add-reminder <titre> [échéance] [liste]") }
    let r = EKReminder(eventStore: store)
    r.title = args[1]
    if args.count > 2, !args[2].isEmpty {
        guard let due = parse(args[2]) else { fail("Date invalide : \(args[2])") }
        var comps = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: due)
        if args[2].count == 10 { comps.hour = nil; comps.minute = nil }
        r.dueDateComponents = comps
        if args[2].count > 10 { r.addAlarm(EKAlarm(absoluteDate: due)) }
    }
    if args.count > 3, !args[3].isEmpty {
        guard let cal = store.calendars(for: .reminder).first(where: { $0.title.lowercased() == args[3].lowercased() })
        else { fail("Liste « \(args[3]) » introuvable.") }
        r.calendar = cal
    } else {
        guard let cal = store.defaultCalendarForNewReminders() else { fail("Aucune liste de rappels par défaut.") }
        r.calendar = cal
    }
    do { try store.save(r, commit: true) } catch { fail("Enregistrement impossible : \(error.localizedDescription)") }
    out(["ok": true, "title": r.title ?? "", "list": r.calendar.title, "due": args.count > 2 ? args[2] : ""])

default:
    fail("commande inconnue : \(cmd)")
}
