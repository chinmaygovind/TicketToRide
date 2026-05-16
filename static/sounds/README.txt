Place sound files here:

  your_turn.mp3   — played when it becomes your turn (you promised to provide this)

The other sounds (draw card, place trains, final round warning) are generated
synthetically via Web Audio API and need no files. If you want custom sounds
for those too, add:

  draw_card.mp3
  place_trains.mp3
  final_round.mp3

The code tries to load your_turn.mp3 first; if it fails (file missing or
browser blocks autoplay), it falls back to a synth chime.
