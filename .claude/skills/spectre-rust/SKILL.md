---
name: spectre-rust
description: La maîtrise du Rust pour Spectre et tous ses agents — ownership, emprunts et durées de vie, types et traits, gestion des erreurs (Result, ?, thiserror/anyhow), collections et itérateurs, génériques, concurrence (threads, Send/Sync, canaux) et async (Tokio), unsafe et FFI, macros, modules, crates et workspaces, tests, benchmarks, documentation, outillage (cargo, clippy, rustfmt, rust-analyzer, cargo-audit) et l'écosystème stable (serde, clap, reqwest, axum, sqlx, tracing, rayon). À charger dès qu'une demande touche du Rust : écrire, relire, corriger, expliquer, porter du code vers Rust, choisir une crate, comprendre une erreur du compilateur ou du borrow checker.
---

# spectre-rust — écrire du Rust juste, sûr et idiomatique

Rust 1.99 stable (édition 2024) est installé sur ce PC avec rustup (toolchain MSVC) : `cargo`,
`clippy`, `rustfmt`, `rust-analyzer`. Les agents vérifient avec l'outil `toolkit` name
`cargo`, cible = le dossier du projet : options `check` (rapide), `clippy` (ajoute `--strict`
pour refuser les avertissements), `test`, `fmt`, `build`, `doc`, `tree`, ou `new` (la cible =
le dossier à créer). **On n'annonce jamais qu'un code compile sans `cargo check` vert.**

## La méthode, à chaque fois
1. **Comprendre le besoin** : binaire ou bibliothèque, cible (Windows, Linux, WASM), contraintes
   (perf, mémoire, `no_std`), et la logique métier du projet (invariants) — elle prime.
2. **Modéliser par les types** : rendre les états impossibles irreprésentables (`enum` à
   variantes porteuses, newtypes `struct UserId(u64)`, `Option` plutôt qu'une valeur sentinelle).
3. **Écrire petit, compiler souvent** : `cargo check` à chaque étape ; lire l'erreur du
   compilateur en entier (elle propose souvent la correction : `help:`).
4. **Tester** : tests unitaires dans `#[cfg(test)] mod tests`, tests d'intégration dans
   `tests/`, doctests dans les `///`. `cargo test` vert avant de livrer.
5. **Polir** : `cargo fmt`, `cargo clippy --strict`, documentation publique (`//!`, `///`).

## Ownership et emprunts (le cœur)
- Une valeur a **un seul propriétaire** ; le déplacement (`move`) est la règle, la copie
  (`Copy`) l'exception (types simples). `clone()` est explicite : acceptable, mais le signaler
  s'il est coûteux.
- Emprunts : **plusieurs `&T` OU un seul `&mut T`**, jamais les deux à la fois. Les durées de
  vie (`'a`) relient la validité d'une référence à celle de sa source ; le compilateur les
  déduit le plus souvent (élision) — n'en écrire que si une fonction renvoie une référence
  issue de plusieurs entrées.
- Erreurs typiques et remèdes : *borrowed value does not live long enough* → rendre la valeur
  propriétaire (`String` au lieu de `&str`) ou élargir sa portée ; *cannot borrow as mutable
  because it is also borrowed as immutable* → raccourcir l'emprunt (bloc, variable
  intermédiaire), ou séparer les champs ; *use of moved value* → emprunter (`&x`), cloner, ou
  restructurer.
- Partage : `Rc<T>` (un fil) / `Arc<T>` (plusieurs fils) ; mutation partagée : `RefCell`
  (un fil) / `Mutex`, `RwLock` (plusieurs fils). Éviter `Rc<RefCell<…>>` partout : c'est
  souvent le signe d'un modèle à revoir (indices dans un `Vec`, arène, propriétaire unique).

## Erreurs
- `Result<T, E>` et l'opérateur `?` ; **jamais `unwrap()`/`expect()` en code de production**
  sauf invariant prouvé (et alors `expect("pourquoi c'est impossible")`).
- Bibliothèque : erreurs typées avec `thiserror` ; application : `anyhow::Result` avec
  `.context("ce qu'on faisait")`. `panic!` = bogue, pas une erreur attendue.

## Types, traits, génériques
- Traits pour les comportements ; `impl Trait` en argument/retour pour rester simple ;
  génériques `fn f<T: Display>(x: T)` ou `where` quand les bornes s'allongent ; `dyn Trait`
  (dans `Box`/`&`) quand le type n'est connu qu'à l'exécution.
- Dériver ce qui sert : `#[derive(Debug, Clone, PartialEq, Eq, Hash, Default)]`,
  `serde::{Serialize, Deserialize}` pour les données échangées.
- Itérateurs plutôt que boucles indexées : `iter().filter().map().collect::<Vec<_>>()`,
  `enumerate`, `zip`, `windows`, `chunks`, `fold` ; ils sont aussi rapides que des boucles.

## Concurrence et async
- Threads : `std::thread::scope` pour emprunter sans `Arc` ; données partagées `Arc<Mutex<T>>`
  ; canaux `std::sync::mpsc` ou `crossbeam`. Parallélisme de données : `rayon` (`par_iter`).
- Async : **Tokio** (`#[tokio::main]`), `async fn`, `.await` ; ne jamais bloquer dans une tâche
  async (`spawn_blocking` pour le CPU ou les E/S bloquantes) ; `tokio::select!`, timeouts.
  Ne pas mélanger plusieurs runtimes.
- `Send`/`Sync` : si le compilateur refuse, c'est presque toujours un `Rc` ou un `RefCell` qui
  traverse un fil : passer à `Arc`/`Mutex`.

## unsafe et FFI
- `unsafe` seulement quand c'est indispensable (FFI, performance prouvée par un benchmark),
  dans un bloc minuscule, commenté `// SAFETY: …` avec l'invariant qui le rend sûr, enveloppé
  dans une API sûre. Vérifier avec `cargo miri test` quand c'est possible.
- FFI C : `extern "C"`, `#[repr(C)]`, `bindgen`/`cbindgen` ; Python : `pyo3` + `maturin` ;
  WASM : `wasm-bindgen`, `wasm-pack`.

## Projet et écosystème (crates stables et maintenues)
- `Cargo.toml` : édition 2024, `rust-version` si l'on vise un MSRV, dépendances avec versions
  explicites ; workspace pour plusieurs crates. `Cargo.lock` commité pour un binaire.
- Crates de référence : `serde`/`serde_json`, `clap` (CLI), `reqwest` (HTTP), `axum` (serveur
  web), `tokio`, `sqlx` ou `rusqlite` (bases), `tracing` (journaux), `rayon`, `regex`,
  `chrono`/`time`, `uuid`, `thiserror`, `anyhow`, `criterion` (benchmarks), `proptest`
  (tests par propriétés). Choisir la plus sûre et la plus maintenue ; vérifier la licence
  (MIT/Apache-2.0 en général) et les failles (`cargo audit` si installé, sinon le signaler).
- Performance : mesurer d'abord (`cargo build --release`, `criterion`) ; éviter les
  allocations inutiles (`&str`, `Cow`, `with_capacity`) ; profil `release` avec `lto = true`
  si la taille ou la vitesse compte.

## Porter du code vers Rust
Partir des tests existants (ou en écrire), traduire module par module, garder la même API
publique tant que possible, remplacer les exceptions par `Result`, les nulls par `Option`,
l'héritage par composition et traits. Mesurer avant d'affirmer « plus rapide ».

## Sécurité et rétro-ingénierie
Un binaire Rust inconnu s'inspecte (Syfer) avec `toolkit` name `retro`, commande
`inspect-rust-binary` (dépendances embarquées par cargo-auditable), sans jamais l'exécuter.

## Compte rendu
Ce qui a été écrit (fichiers), la sortie de `cargo check`/`clippy`/`test` (vert ou non),
les choix de crates et pourquoi, et ce qui reste à vérifier par l'utilisateur.
