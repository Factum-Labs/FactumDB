//! Window-owned Windows Hello consent. No OS credentials enter the application.
use windows::{
    core::{factory, HSTRING},
    Security::Credentials::UI::{
        UserConsentVerificationResult, UserConsentVerifier, UserConsentVerifierAvailability,
    },
    Win32::{
        Foundation::HWND,
        System::WinRT::{
            IUserConsentVerifierInterop, RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED,
        },
    },
};
use windows_future::IAsyncOperation;

struct Apartment;
impl Drop for Apartment {
    fn drop(&mut self) {
        unsafe {
            RoUninitialize();
        }
    }
}

fn verification_result(result: UserConsentVerificationResult) -> Result<(), String> {
    match result {
        UserConsentVerificationResult::Verified => Ok(()),
        UserConsentVerificationResult::Canceled => Err("Windows Hello verification was cancelled.".into()),
        UserConsentVerificationResult::NotConfiguredForUser => Err("Set up a Windows Hello PIN, fingerprint or face recognition in Windows Settings, then try again.".into()),
        UserConsentVerificationResult::DeviceNotPresent => Err("Windows Hello is unavailable on this device.".into()),
        UserConsentVerificationResult::DisabledByPolicy => Err("Windows Hello is disabled by your device's security policy.".into()),
        UserConsentVerificationResult::DeviceBusy => Err("Windows Hello is busy. Try again.".into()),
        UserConsentVerificationResult::RetriesExhausted => Err("Windows Hello verification attempts were exhausted. Try again later.".into()),
        _ => Err("Windows Hello did not approve verification.".into()),
    }
}

pub fn verify(window_handle: isize) -> Result<(), String> {
    if window_handle == 0 {
        return Err("Windows Hello needs an active FactumDB window.".into());
    }
    // Called on a blocking worker so waiting for the OS does not block the UI.
    unsafe { RoInitialize(RO_INIT_MULTITHREADED) }
        .map_err(|e| format!("Cannot initialize Windows Hello: {e}"))?;
    let _apartment = Apartment;
    let availability = UserConsentVerifier::CheckAvailabilityAsync()
        .and_then(|operation| operation.get())
        .map_err(|e| format!("Cannot check Windows Hello availability: {e}"))?;
    match availability {
        UserConsentVerifierAvailability::Available => {}
        UserConsentVerifierAvailability::NotConfiguredForUser => {
            return verification_result(UserConsentVerificationResult::NotConfiguredForUser)
        }
        UserConsentVerifierAvailability::DeviceNotPresent => {
            return verification_result(UserConsentVerificationResult::DeviceNotPresent)
        }
        UserConsentVerifierAvailability::DisabledByPolicy => {
            return verification_result(UserConsentVerificationResult::DisabledByPolicy)
        }
        UserConsentVerifierAvailability::DeviceBusy => {
            return verification_result(UserConsentVerificationResult::DeviceBusy)
        }
        _ => return Err("Windows Hello is unavailable on this device.".into()),
    }
    let interop: IUserConsentVerifierInterop =
        factory::<UserConsentVerifier, IUserConsentVerifierInterop>()
            .map_err(|e| format!("Cannot open Windows Hello: {e}"))?;
    let operation: IAsyncOperation<UserConsentVerificationResult> = unsafe {
        interop.RequestVerificationForWindowAsync(
            HWND(window_handle as *mut _),
            &HSTRING::from("Verify using your device's security to create a FactumDB account."),
        )
    }
    .map_err(|e| format!("Cannot open Windows Hello: {e}"))?;
    verification_result(
        operation
            .get()
            .map_err(|e| format!("Windows Hello verification failed: {e}"))?,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_verified_native_result_is_accepted() {
        assert!(verification_result(UserConsentVerificationResult::Verified).is_ok());
        for result in [
            UserConsentVerificationResult::Canceled,
            UserConsentVerificationResult::DeviceNotPresent,
            UserConsentVerificationResult::NotConfiguredForUser,
            UserConsentVerificationResult::DisabledByPolicy,
            UserConsentVerificationResult::DeviceBusy,
            UserConsentVerificationResult::RetriesExhausted,
            UserConsentVerificationResult(-1),
        ] {
            assert!(verification_result(result).is_err());
        }
        assert!(verify(0).is_err());
    }
}
