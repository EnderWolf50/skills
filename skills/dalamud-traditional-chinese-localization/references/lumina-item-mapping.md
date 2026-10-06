# Lumina item mapping on Traditional Chinese clients

Use when a Dalamud plugin resolves Lumina rows or external item names with a forced English language (`GetRow<Item>(..., ClientLanguage.English)`, `GetExcelSheet<T>(Language.English)`) and therefore breaks on a client without that language pack, or when a workshop or schedule importer maps English bot names to game items. The durable idea: language-independent row identity is separate from localized display text. This pattern needs the plugin's matching Lumina data and an authoritative, version-scoped external-name map; it does not translate arbitrary text or guarantee IDs across mismatched game-data versions.

## Quick reference

```text
Forced client language: ClientLanguage.English
Forced Lumina language: Language.English
Localized/default sheet: GameData.GetExcelSheet<T>()
Row lookup: GameData.GetExcelSheet<T>()?.GetRowOrDefault(rowId)
Stable seam: external name <-> row ID
Display name: localized Item.Name, then external-name fallback
Sparse index size: max(local row IDs) + 1
Unknown ID behaviour: explicit empty/missing result
```

## Procedure

1. **Trace the complete item flow.**
   Search the affected module for:

   ```text
   ClientLanguage.English
   Language.English
   GetExcelSheet<
   GetRow<
   Item.Value.Name
   RowId
   ```

   Follow input parsing, favor/bot command generation, UI display, solver data, and scheduling calls. Done when every transition among external name, Lumina row, localized name, and game action is identified.

2. **Classify each sheet access.**
   Treat `MJICraftworksObject`, popularity, pouch, cycle, and similar structural sheets as row data, not English text catalogs. Fetch them with the client/default overload:

   ```csharp
   var sheet = gameData.GetExcelSheet<MJICraftworksObject>();
   var row = gameData.GetExcelSheet<MJICraftworksPopularity>()?.GetRowOrDefault(rowId);
   ```

   Reserve explicit language selection for a proven text requirement whose sheet actually exists on that client. Done when structural logic no longer depends on an English sheet.

3. **Put a row-ID adapter at the external-name seam.**
   External schedules and Discord bots may require fixed English names even when the client cannot load English data. Store those names by language-independent craft row ID in a pure module:

   ```csharp
   internal static class WorkshopItemNames
   {
       private static readonly IReadOnlyDictionary<uint, string> ExternalNames =
           new Dictionary<uint, string>
           {
               [1] = "Potion",
               [33] = "Squid Ink",
               [77] = "Mammet Award",
           };

       public static string ExternalName(uint rowId) =>
           ExternalNames.GetValueOrDefault(rowId, "");
   }
   ```

   Generate or transcribe this map only from the named authoritative source and record its target data version. Done when runtime external-name resolution requires no `Item` sheet in English.

4. **Build sparse indexes by `RowId`.**
   Lumina enumeration order is not an interface guarantee. When existing parsing indexes names by numeric row ID, allocate by the maximum local ID and fill explicit slots:

   ```csharp
   var ids = craftSheet.Select(row => row.RowId).Distinct().ToList();
   var names = Enumerable.Repeat("", checked((int)ids.DefaultIfEmpty(0u).Max() + 1)).ToList();
   foreach (var id in ids)
       names[checked((int)id)] = WorkshopItemNames.ExternalName(id);
   ```

   Intersect the authoritative map with IDs present in the local sheet; unknown or newer IDs remain explicit misses. Done when `names[(int)rowId]` resolves by row identity rather than enumeration position.

5. **Separate parser names from display names.**
   Parse external recommendations with the fixed external name, but render the local linked `Item.Name`:

   ```csharp
   var localName = craftRow.Item.Value.Name.ToString();
   ImGui.TextUnformatted(string.IsNullOrEmpty(localName)
       ? WorkshopItemNames.ExternalName(craftRow.RowId)
       : localName);
   ```

   Generate external bot commands from the fixed map, not localized text. Done when the parser remains compatible with its source format while the UI displays Traditional Chinese data when available.

6. **Remove indirect forced-English helpers from the feature.**
   Convenience methods such as `LuminaSheet<T>()` or `LuminaRow<T>()` may hide `GetExcelSheet<T>(Language.English)`. At localization-sensitive call sites, use the default sheet directly or introduce a clearly named default-language helper. Done when a search finds no forced-English lookup in the adapted feature.

7. **Test the pure mapping before plugin runtime.**
   Create a temporary .NET console project in the OS temp directory, link the pure mapping source, and assert representative first, middle, renamed, last, and unknown IDs. Remove the temporary project afterwards. Done when all expected IDs resolve, unknown IDs follow the documented fallback, and the temporary files are gone.

8. **Build, package, and disclose limits.**
   Restore, build, and verify the packaged manifest per `dalamud-plugin-build`. Report compile warnings separately from errors. Done when the requested Dalamud API is packaged and final Traditional Chinese in-game validation is explicitly distinguished from static and build verification.

## Pitfalls

- `RowId` is language-independent only within compatible game-data content; Taiwan and global clients on different patches may have different available rows.
- `GetExcelSheet<T>()` is correct for structural and default-client data; forcing `Language.English` returns null or throws when that language pack is absent.
- A map from names to IDs is inverted once into an ID-keyed runtime adapter. Localized names are presentation, not identity.
- `sheet.Select(...).ToList()[rowId]` silently assumes dense, ordered rows. Build an explicit sparse index instead.
- English external input and Traditional Chinese UI are separate requirements. Supporting pasted Chinese schedules needs a second localized parser index and real sample input.
- A successful build cannot prove the Traditional Chinese client contains every linked row. Verify the feature in game before claiming full runtime compatibility.
- Keep version-specific mappings near the consuming module and test their expected range; one patch's IDs are not a global Lumina rule.
