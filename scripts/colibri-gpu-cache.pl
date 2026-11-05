#!/usr/bin/env perl
# Reads or changes the GPU cache cap kept in Colibri's saved settings
# (setup.json), as the COLI_VK_TIER_GB entry of its "env" object. Every
# `coli start` passes that object to the server, so the cap applies however
# Colibri is started. `coli setup` rebuilds the object, so
# scripts/install-colibri.sh writes the cap again after each setup.
#
#   colibri-gpu-cache.pl get <setup.json>          prints the cap, or nothing
#   colibri-gpu-cache.pl set <setup.json> <GiB>
#   colibri-gpu-cache.pl unset <setup.json>
#
# get prints nothing when the file or the entry is missing. set and unset
# exit 1 with a message when the file is missing or not shaped as expected,
# and leave it untouched.

use strict;
use warnings;
use JSON::PP ();
use File::Temp ();
use File::Basename qw(dirname);

my $KEY = 'COLI_VK_TIER_GB';
my ($action, $path, $value) = @ARGV;
die "usage: $0 get|set|unset <setup.json> [GiB]\n"
    unless $action && $path && $action =~ /\A(?:get|set|unset)\z/ && (($action eq 'set') == defined $value);

my $json = JSON::PP->new->utf8->canonical->pretty;

sub load {
    my ($quiet) = @_;
    my $text = do { local $/; open my $fh, '<', $path or return fail($quiet, "cannot read $path: $!"); <$fh> };
    my $cfg = eval { $json->decode($text) };
    return fail($quiet, "$path is not JSON Colibri could have written") unless ref $cfg eq 'HASH';
    return fail($quiet, "$path has no \"env\" object; this Colibri keeps its settings differently")
        unless ref $cfg->{env} eq 'HASH';
    return $cfg;
}

sub fail {
    my ($quiet, $message) = @_;
    exit 0 if $quiet;
    print STDERR "$message\n";
    exit 1;
}

if ($action eq 'get') {
    my $cfg = load(1);
    print "$cfg->{env}{$KEY}\n" if defined $cfg->{env}{$KEY};
    exit 0;
}

fail(0, "the cap must be a number of GiB, such as 2.5: $value")
    if $action eq 'set' && $value !~ /\A[0-9]+(?:\.[0-9]+)?\z/;

my $cfg = load(0);
if ($action eq 'set') { $cfg->{env}{$KEY} = "$value" }
else                  { delete $cfg->{env}{$KEY} }

# Write beside the file and rename over it, so a failure leaves the old one.
my $tmp = File::Temp->new(DIR => dirname($path), UNLINK => 0);
print {$tmp} $json->encode($cfg);
close $tmp or die "cannot write $tmp: $!\n";
chmod +(stat $path)[2] & 07777, $tmp->filename;
rename $tmp->filename, $path or die "cannot replace $path: $!\n";
