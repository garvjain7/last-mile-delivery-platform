import { escapeHTML } from "../state.js";

export function captureException(stop) {
    return new Promise((resolve) => {
        const dialog = document.createElement("dialog");
        dialog.className = "action-dialog";
        dialog.innerHTML = `<form id="exception-form" method="dialog">
            <button class="dialog-close" type="button" data-exception-close aria-label="Close">×</button>
            <p class="eyebrow">DELIVERY EXCEPTION</p><h2>What happened?</h2>
            <p class="dialog-copy">${escapeHTML(stop.recipient)} · ${escapeHTML(stop.address)}</p>
            <fieldset class="failure-reason-fieldset"><legend class="field-label">Choose a reason</legend>
                <div class="failure-reason-grid">
                    <label class="failure-reason-option"><input name="failure_reason" type="radio" value="recipient_unavailable" checked><span>Recipient unavailable</span></label>
                    <label class="failure-reason-option"><input name="failure_reason" type="radio" value="wrong_address"><span>Wrong address</span></label>
                    <label class="failure-reason-option"><input name="failure_reason" type="radio" value="refused"><span>Delivery refused</span></label>
                    <label class="failure-reason-option"><input name="failure_reason" type="radio" value="other"><span>Other</span></label>
                </div>
            </fieldset>
            <label class="field-label" for="failure-notes">Notes (optional)</label>
            <textarea id="failure-notes" name="failure_notes" class="text-input" maxlength="500" rows="3"></textarea>
            <label class="field-label" for="exception-photo">Photo (optional)</label>
            <input id="exception-photo" name="photo" class="text-input" type="file" accept="image/jpeg,image/png,image/webp" capture="environment">
            <div id="exception-error" class="form-error" role="alert" hidden></div>
            <label class="check-label"><input name="return_to_hub" type="checkbox"><span>Mark order as returned to hub</span></label>
            <section class="return-queue-notice"><strong>Return queue</strong><span>Physical return handoff is not tracked by the current service.</span></section>
            <p class="dialog-footnote">Return dispatch and photo references are not stored in the current database schema.</p>
            <div class="dialog-actions">
                <button class="button button-secondary" type="button" data-exception-close>Cancel</button>
                <button class="button button-primary" type="submit">Save exception</button>
            </div>
        </form>`;
        document.body.append(dialog);
        const form = dialog.querySelector("#exception-form");
        let result = null;
        const syncFailureSelection = () => {
            dialog.querySelectorAll(".failure-reason-option").forEach((option) => {
                option.classList.toggle("is-selected", option.querySelector("input").checked);
            });
        };
        const close = (value = null) => {
            result = value;
            dialog.close();
        };
        dialog.querySelectorAll('[name="failure_reason"]').forEach((input) => {
            input.addEventListener("change", syncFailureSelection);
        });
        syncFailureSelection();
        dialog.querySelectorAll("[data-exception-close]").forEach((button) => {
            button.addEventListener("click", () => close());
        });
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            const values = new FormData(form);
            const photo = values.get("photo");
            const error = dialog.querySelector("#exception-error");
            if (photo instanceof File && photo.size > 0 && photo.size > 5 * 1024 * 1024) {
                error.textContent = "Exception photos must be 5 MB or smaller.";
                error.hidden = false;
                return;
            }
            if (
                photo instanceof File
                && photo.size > 0
                && !["image/jpeg", "image/png", "image/webp"].includes(photo.type)
            ) {
                error.textContent = "Choose a JPEG, PNG, or WebP photo.";
                error.hidden = false;
                return;
            }
            close({
                failureReason: values.get("failure_reason"),
                failureNotes: values.get("failure_notes").trim(),
                returnToHub: values.has("return_to_hub"),
                photo
            });
        });
        dialog.addEventListener("close", () => {
            dialog.remove();
            resolve(result);
        }, { once: true });
        dialog.showModal();
    });
}
