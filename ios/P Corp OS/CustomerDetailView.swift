import SwiftUI
import PCorpKit

/// iOS port of desktop's own CustomerDetailView.swift -- see that file's
/// docstring for the full reasoning (Phase 3, 2026-09-24). Presented as
/// a `.sheet(item:)` from VentureDetailView, matching this app's own
/// sheet-with-NavigationStack precedent.
struct CustomerDetailView: View {
    let venture: Venture
    let customer: Customer
    @ObservedObject var client: VenturesClient
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var toastCenter: ToastCenter

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(customer.name)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                    }
                }
        }
        .presentationDetents([.large])
        .task {
            await client.fetchRevenueEvents(ventureId: venture.id, customerId: customer.id)
            await client.fetchFulfillmentItems(ventureId: venture.id, customerId: customer.id)
        }
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: 0) {
            Menu(customer.status.capitalized) {
                ForEach(customerStatusOptions, id: \.self) { status in
                    Button(status.capitalized) { Task { await client.updateCustomerStatus(ventureId: venture.id, customerId: customer.id, status: status) } }
                }
            }
            .font(PCorpFont.body(12))
            .padding(.horizontal, 16)
            .padding(.top, 8)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let error = client.errorMessage { errorText(error) }
                    revenueSection
                    Divider().overlay(theme.divider).padding(.vertical, 4)
                    fulfillmentSection
                }
                .padding(16)
            }
        }
        .background(theme.background)
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.label(10))
            .trackedLabel(1.1)
            .foregroundStyle(theme.textSecondary)
    }

    private func errorText(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.body(12))
            .foregroundStyle(theme.statusRisk)
    }

    // MARK: - Revenue

    @State private var newAmount = ""
    @State private var newEventType = "charge"
    @State private var newNotes = ""

    @ViewBuilder
    private var revenueSection: some View {
        sectionLabel("LOG REVENUE")
        VStack(alignment: .leading, spacing: 8) {
            TextField("Amount", text: $newAmount)
                .textFieldStyle(.plain).font(PCorpFont.body(12.5)).padding(10).cardSurface(radius: 8)
            Picker("Type", selection: $newEventType) {
                ForEach(revenueEventTypeOptions, id: \.self) { Text($0.capitalized).tag($0) }
            }
            TextField("Notes (optional)", text: $newNotes)
                .textFieldStyle(.plain).font(PCorpFont.body(12.5)).padding(10).cardSurface(radius: 8)
            AsyncButton(action: logRevenue) {
                Text("Log Event")
            }
            .buttonStyle(.borderedProminent)
            .disabled(Double(newAmount) == nil)
        }
        .padding(12)
        .cardSurface(radius: 10)

        Divider().overlay(theme.divider).padding(.vertical, 4)

        sectionLabel("REVENUE HISTORY")
        if client.revenueEvents.isEmpty {
            Text("No revenue events logged yet.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(client.revenueEvents) { event in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(event.eventType == "charge" ? "+R\(String(format: "%.2f", event.amount))" : "-R\(String(format: "%.2f", event.amount))")
                                .font(PCorpFont.body(12, weight: .semibold))
                                .foregroundStyle(event.eventType == "charge" ? theme.statusGood : theme.statusRisk)
                            if let notes = event.notes, !notes.isEmpty {
                                Text(notes).font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
                            }
                        }
                        Spacer()
                        Text(event.occurredAt)
                            .font(PCorpFont.body(10))
                            .foregroundStyle(theme.textTertiary)
                    }
                    .padding(8)
                    .cardSurface(radius: 6)
                }
            }
        }
    }

    private func logRevenue() async {
        guard let amount = Double(newAmount) else { return }
        await client.logRevenueEvent(
            ventureId: venture.id, customerId: customer.id, amount: amount,
            eventType: newEventType, notes: newNotes.isEmpty ? nil : newNotes
        )
        newAmount = ""; newNotes = ""
        toastCenter.show("Revenue event logged", style: .success)
    }

    // MARK: - Fulfillment

    @State private var newItemTitle = ""

    @ViewBuilder
    private var fulfillmentSection: some View {
        sectionLabel("FULFILMENT CHECKLIST")
        if client.fulfillmentItems.isEmpty {
            Text("No fulfilment steps yet -- add what needs to happen to deliver this sale.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(client.fulfillmentItems) { item in
                    FulfillmentItemRow(
                        item: item,
                        onStatusChange: { newStatus in
                            Task { await client.updateFulfillmentItemStatus(ventureId: venture.id, customerId: customer.id, itemId: item.id, status: newStatus) }
                        },
                        onDelete: { Task { await client.deleteFulfillmentItem(ventureId: venture.id, customerId: customer.id, itemId: item.id) } }
                    )
                }
            }
        }
        HStack(spacing: 8) {
            TextField("Add a fulfilment step", text: $newItemTitle)
                .textFieldStyle(.plain).font(PCorpFont.body(12.5)).padding(10).cardSurface(radius: 8)
            AsyncButton(action: addFulfillmentItem) {
                Text("Add")
            }
            .buttonStyle(.bordered)
            .disabled(newItemTitle.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }

    private func addFulfillmentItem() async {
        let title = newItemTitle.trimmingCharacters(in: .whitespaces)
        guard !title.isEmpty else { return }
        await client.addFulfillmentItem(ventureId: venture.id, customerId: customer.id, title: title)
        newItemTitle = ""
    }
}

private struct FulfillmentItemRow: View {
    let item: FulfillmentItem
    let onStatusChange: (String) -> Void
    let onDelete: () -> Void
    @Environment(\.appTheme) private var theme

    private var statusColor: Color {
        switch item.status {
        case "done": return theme.statusGood
        case "skipped": return theme.textTertiary
        default: return theme.statusHot
        }
    }

    var body: some View {
        HStack(spacing: 8) {
            Text(item.title)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textPrimary)
            Spacer()
            Menu(item.status.capitalized) {
                ForEach(checklistItemStatusOptions, id: \.self) { status in
                    Button(status.capitalized) { onStatusChange(status) }
                }
            }
            .font(PCorpFont.body(10.5))
            .foregroundStyle(statusColor)
            Button(action: onDelete) {
                Image(systemName: "trash")
                    .font(.system(size: 10))
                    .foregroundStyle(theme.textTertiary)
            }
            .buttonStyle(.plain)
        }
        .padding(8)
        .cardSurface(radius: 6)
    }
}
