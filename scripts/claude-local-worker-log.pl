#!/usr/bin/env perl
# Reads Claude Code's step-by-step output (claude -p --output-format
# stream-json --verbose) on stdin. Writes one readable line per step to the
# log file named in the first argument, so `tail -F` on it shows the worker
# as it goes, and prints only the worker's final report to stdout.
#
#   claude -p ... --output-format stream-json --verbose | claude-local-worker-log.pl run.log
#
# Exits 1 if the stream ends without a final report.

use strict;
use warnings;
use JSON::PP ();
use POSIX qw(strftime);

my $SHOW_LINES = 12;    # lines of tool output, or of an edit, shown per step

my $log_path = shift or die "usage: $0 <log file>\n";
open my $log, '>>:encoding(UTF-8)', $log_path or die "cannot write $log_path: $!\n";
$log->autoflush(1);
binmode STDOUT, ':encoding(UTF-8)';

my $json = JSON::PP->new->utf8;
my %tool_name;    # tool_use id => tool name, to label each result
my $report;

sub stamp { strftime('%H:%M:%S', localtime) }

# One step line, then any detail lines indented under it.
sub step {
    my ($label, $first, @detail) = @_;
    my $head = sprintf "%s  %-7s %s", stamp(), $label, $first // q{};
    $head =~ s/\s+\z//;
    print {$log} "$head\n";
    print {$log} "                  $_\n" for @detail;
}

# The first $SHOW_LINES lines of $text, each with $prefix, and a count of the rest.
sub some_lines {
    my ($text, $prefix) = @_;
    $prefix //= '';
    my @lines = split /\n/, $text // '', -1;
    pop @lines while @lines && $lines[-1] eq '';
    my @shown = map { "$prefix$_" } @lines[0 .. ($#lines < $SHOW_LINES - 1 ? $#lines : $SHOW_LINES - 1)];
    push @shown, sprintf('... %d more lines', @lines - $SHOW_LINES) if @lines > $SHOW_LINES;
    return @shown;
}

sub tool_call {
    my ($block) = @_;
    my $name = $block->{name} // '?';
    my $in = $block->{input} // {};
    $tool_name{ $block->{id} // '' } = $name;

    if ($name eq 'Bash') {
        my ($first, @rest) = split /\n/, $in->{command} // '';
        return step('Bash', '$ ' . ($first // ''), map {"  $_"} @rest);
    }
    if ($name eq 'Edit') {
        return step('Edit', $in->{file_path},
            some_lines($in->{old_string}, '- '), some_lines($in->{new_string}, '+ '));
    }
    if ($name eq 'Write') {
        my $count = () = ($in->{content} // '') =~ /\n/g;
        return step('Write', "$in->{file_path} ($count lines)");
    }
    if ($name eq 'Read') {
        return step('Read', $in->{file_path});
    }
    if ($name eq 'Glob' || $name eq 'Grep') {
        return step($name, join ' in ', grep {defined} $in->{pattern}, $in->{path});
    }
    return step($name, JSON::PP->new->canonical->encode($in));
}

sub tool_result {
    my ($block) = @_;
    my $content = $block->{content};
    $content = join "\n", map { ref $_ ? $_->{text} // '' : $_ } @$content if ref $content eq 'ARRAY';
    my $name = $tool_name{ $block->{tool_use_id} // '' } // 'tool';
    # Read, Edit, and Write results only repeat the file name, or the whole
    # file; the step line already says which file. Their errors still show.
    return if $name =~ /\A(?:Read|Edit|Write)\z/ && !$block->{is_error};
    my @lines = some_lines($content);
    return unless @lines;
    print {$log} '                ' . ($block->{is_error} ? '! ' : '  ') . "$_\n" for @lines;
}

while (my $line = <STDIN>) {
    next unless $line =~ /\S/;
    my $event = eval { $json->decode($line) };
    if (!$event) {
        step('?', $line =~ s/\s+\z//r);
        next;
    }
    my $type = $event->{type} // '';
    if ($type eq 'system' && ($event->{subtype} // '') eq 'init') {
        step('start', "model $event->{model} in $event->{cwd}");
    }
    elsif ($type eq 'assistant') {
        for my $block (@{ $event->{message}{content} // [] }) {
            my $kind = $block->{type} // '';
            if    ($kind eq 'tool_use') { tool_call($block) }
            elsif ($kind eq 'text')     { step('says', undef, some_lines($block->{text})) if $block->{text} =~ /\S/ }
            elsif ($kind eq 'thinking') { step('thinks', undef, some_lines($block->{thinking})) if ($block->{thinking} // '') =~ /\S/ }
        }
    }
    elsif ($type eq 'user') {
        my $content = $event->{message}{content};
        next unless ref $content eq 'ARRAY';
        tool_result($_) for grep { ($_->{type} // '') eq 'tool_result' } @$content;
    }
    elsif ($type eq 'result') {
        $report = $event->{result} // '';
        my $seconds = int(($event->{duration_ms} // 0) / 1000);
        step('done', sprintf('%s after %d turns in %dm%02ds',
            $event->{is_error} ? 'FAILED' : 'finished', $event->{num_turns} // 0, $seconds / 60, $seconds % 60));
    }
}

if (!defined $report) {
    step('done', 'stopped without a final report');
    print STDERR "the worker stopped without a final report; see $log_path\n";
    exit 1;
}
print $report, ($report =~ /\n\z/ ? '' : "\n");
