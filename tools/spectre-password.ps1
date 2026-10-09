# Choose the password that protects Spectre's interface when it is reachable from the phone.
# It is stored in your Windows user environment (SPECTRE_WEBUI_PASSWORD), never in the repository.
# Used by tools\spectre-password.cmd. An empty answer removes the password (local use only).
$first = Read-Host "Nouveau mot de passe de Spectre (vide = le supprimer)" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($first))
if (-not $plain) {
    [Environment]::SetEnvironmentVariable("SPECTRE_WEBUI_PASSWORD", $null, "User")
    Write-Host "Mot de passe supprimé : Spectre ne sera plus joignable depuis le téléphone."
} else {
    $again = Read-Host "Confirme le mot de passe" -AsSecureString
    $check = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($again))
    if ($check -ne $plain) {
        Write-Host "Les deux mots de passe sont différents : rien n'a changé."
    } elseif ($plain.Length -lt 8) {
        Write-Host "Trop court : choisis au moins 8 caractères. Rien n'a changé."
    } else {
        [Environment]::SetEnvironmentVariable("SPECTRE_WEBUI_PASSWORD", $plain, "User")
        Write-Host "Mot de passe enregistré. Arrête puis relance Spectre pour l'appliquer."
    }
}
Read-Host "Appuie sur Entrée pour fermer"
