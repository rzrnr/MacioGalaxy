#pragma once
// Host crash reporting.
//
// On the Wii, CPU exceptions reach handlers registered with OSSetErrorHandler
// with an OSContext holding the PowerPC registers (JUTException prints them on
// screen). Natively there are no PowerPC exceptions or registers: faults are
// host signals with arm64 state. install() catches fatal signals (SIGSEGV,
// SIGBUS, SIGILL, SIGFPE, SIGTRAP, SIGABRT) and writes a report of the true
// host state:
// - signal, code, and fault address;
// - arm64 registers (x0-x28, fp, lr, sp, pc), labelled as host registers;
// - a host backtrace;
// - the running OS thread and whether the fault was in interrupt context;
// - the last OSPanic/OSFatal message and recent OSReport lines;
// - the last fatal host message (recordFatalMessage), such as the renderer's
//   reason for giving up;
// - the game error handlers registered with OSSetErrorHandler.
// The signal is then re-raised with its default action. Game error handlers
// are not called: they expect a PowerPC context this port cannot provide
// truthfully.

#include <cstddef>
#include <filesystem>

namespace PetariNative::Platform::Crash {

// Installs the signal handlers (on an alternate stack). Reports go to stderr
// and, if reportDirectory is not empty, to petari-crash-<time>-<pid>.txt in it
// (the directory must exist). Call once from the main thread at start-up.
void install(const std::filesystem::path& reportDirectory);

// Path of the report file the next crash will write (empty if none).
std::filesystem::path reportPath();

// Keeps a fatal message from host code that is about to abort (Aurora's
// LOG_FATAL, e.g. Dawn's shader compile error) for the report, which prints it
// in full up to 4 KiB. module names its source.
void recordFatalMessage(const char* module, const char* message, std::size_t length);

}  // namespace PetariNative::Platform::Crash
