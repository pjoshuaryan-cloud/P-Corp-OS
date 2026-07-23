import SwiftUI

struct WarRoomView: View {
    @State private var inputText: String = ""

    var body: some View {
        VStack(spacing: 0) {
            topBar

            Spacer(minLength: 0)

            VStack(alignment: .leading, spacing: 12) {
                Text("Good morning, Joshua.")
                    .font(.system(size: 34, weight: .semibold))
                Text("I'm Frank. How can I help you today?")
                    .font(.system(size: 17))
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 48)

            Spacer(minLength: 24)

            FrankOrb()
                .frame(width: 220, height: 220)

            Spacer(minLength: 32)

            inputBar
                .padding(.horizontal, 48)
                .padding(.bottom, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.white)
    }

    private var topBar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Good morning, Joshua.")
                    .font(.system(size: 13, weight: .medium))
                Text(Date.now.formatted(date: .complete, time: .omitted))
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Image(systemName: "p.square")
                .font(.system(size: 16))
                .foregroundStyle(.secondary)

            Spacer()

            HStack(spacing: 16) {
                Image(systemName: "magnifyingglass")
                Image(systemName: "waveform.circle.fill")
                Button {
                    // no-op: shell only, not wired up yet
                } label: {
                    Label("New Task", systemImage: "plus")
                        .font(.system(size: 12, weight: .medium))
                }
                .buttonStyle(.borderedProminent)
                .tint(.black)
            }
            .font(.system(size: 15))
            .foregroundStyle(.primary)
        }
        .padding(.horizontal, 32)
        .padding(.vertical, 20)
    }

    private var inputBar: some View {
        HStack(spacing: 12) {
            Image(systemName: "waveform")
                .foregroundStyle(.secondary)
            TextField("Talk to Frank...", text: $inputText)
                .textFieldStyle(.plain)
                .font(.system(size: 14))

            Button {
                // no-op: shell only, not wired up yet
            } label: {
                Image(systemName: "arrow.up")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 32, height: 32)
                    .background(Circle().fill(Color.black))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 24)
                .fill(Color(white: 0.97))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 24)
                .strokeBorder(Color.black.opacity(0.08))
        )
    }
}

/// A restrained, static stand-in for Frank's presence — no glow, no animation yet.
/// Deliberately not a mascot: FOUNDER_BRIEF.md and UI_GUIDELINES.md are explicit
/// that Frank's presence should come from behavior, not a character on screen.
private struct FrankOrb: View {
    var body: some View {
        Circle()
            .fill(Color.black)
            .overlay(
                Circle()
                    .fill(Color.white.opacity(0.06))
                    .blur(radius: 20)
                    .offset(x: -30, y: -30)
            )
            .clipShape(Circle())
    }
}
